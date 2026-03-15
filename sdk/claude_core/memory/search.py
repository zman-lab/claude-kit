"""
메모리 검색 엔진.
FTS5 전문 검색 + 시간 감쇠 점수 + 조건부 Claude 재랭킹.

의존성 분리 (원본 대비 변경사항):
    - settings → MemoryConfig로 교체
    - HALF_LIVES, TYPE_PRIORITY → MemoryConfig에서 주입
"""
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from .config import MemoryConfig
from .models import MemoryItem, MemorySearchResult
from .storage import MemoryStorage

logger = logging.getLogger(__name__)

# 한국어 조사 제거 패턴
_KO_JOSA_RE = re.compile(
    r"(을|를|이|가|은|는|에|에서|에게|으로|로|와|과|의|도|만|부터|까지|처럼|보다|으로서|로서)$"
)

# FTS5 예약어 이스케이프
_FTS_SPECIAL_RE = re.compile(r'["\\\']')


def _extract_korean_subwords(word: str) -> list[str]:
    """3글자 이상 한국어 단어에서 2글자 서브스트링을 추출한다 (간단한 n-gram)."""
    if len(word) < 3:
        return [word]
    subs = [word]
    for size in range(2, len(word)):
        for i in range(len(word) - size + 1):
            sub = word[i:i + size]
            if sub != word and sub not in subs:
                subs.append(sub)
    return subs


def _extract_keywords(query: str) -> list[str]:
    """쿼리에서 검색 키워드를 추출한다."""
    tokens = re.split(r"[\s,，。．!！?？;；:：\(\)\[\]]+", query.strip())
    keywords = []
    for token in tokens:
        if not token:
            continue
        token = _KO_JOSA_RE.sub("", token)
        if len(token) >= 2:
            for kw in _extract_korean_subwords(token):
                if kw not in keywords:
                    keywords.append(kw)
    return keywords[:15]


def _build_fts_query(keywords: list[str]) -> str:
    """FTS5 MATCH 쿼리 구성."""
    if not keywords:
        return ""
    escaped = [f'"{_FTS_SPECIAL_RE.sub("", kw)}"*' for kw in keywords if kw]
    return " OR ".join(escaped)


def calc_decay(
    memory_type: str,
    updated_at: Optional[datetime],
    metadata: dict,
    half_lives: dict[str, Optional[float]],
) -> float:
    """시간 감쇠 인자 계산 (lazy, DB 쓰기 없음).

    Args:
        memory_type: 메모리 타입 문자열
        updated_at: 마지막 업데이트 시각
        metadata: 메모리 메타데이터
        half_lives: 타입별 반감기 딕셔너리 (MemoryConfig.half_lives)
    """
    # critical failure는 감쇠 면제
    if memory_type == "failure":
        severity = metadata.get("severity", "")
        if severity == "critical":
            return 1.0

    half_life = half_lives.get(memory_type)
    if half_life is None:
        return 1.0

    if updated_at is None:
        return 1.0

    # 경과 일수 계산
    now = datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    days_elapsed = (now - updated_at).total_seconds() / 86400.0

    if days_elapsed <= 0:
        return 1.0

    decay = 0.5 ** (days_elapsed / half_life)
    return max(decay, 0.01)  # 최솟값 0.01


class MemorySearcher:
    """메모리 검색기. FTS5 + 감쇠 점수 + 재랭킹."""

    def __init__(self, storage: MemoryStorage, config: MemoryConfig):
        self._storage = storage
        self._config = config

    async def search(
        self,
        query: str,
        type_filter: Optional[str] = None,
    ) -> list[MemorySearchResult]:
        """
        메모리 검색 5단계 파이프라인.
        1. 키워드 추출
        2. FTS5 쿼리 구성
        3. failure/tool 타입 우선 정렬
        4. 감쇠 점수 적용
        5. 상위 N개 반환 + accessed_at 갱신
        """
        keywords = _extract_keywords(query)
        if not keywords:
            return []

        fts_query = _build_fts_query(keywords)
        if not fts_query:
            return []

        try:
            async with aiosqlite.connect(self._storage._db_path) as conn:
                await conn.execute("PRAGMA journal_mode=WAL")
                conn.row_factory = aiosqlite.Row

                sql = """
                    SELECT m.*, -fts.rank AS fts_score
                    FROM memories_fts fts
                    JOIN memories m ON m.id = fts.rowid
                    WHERE memories_fts MATCH ?
                      AND m.is_active = 1
                """
                params: list = [fts_query]

                if type_filter:
                    sql += " AND m.type = ?"
                    params.append(type_filter)

                sql += " ORDER BY fts_score DESC LIMIT 50"

                cursor = await conn.execute(sql, params)
                rows = await cursor.fetchall()
        except Exception as e:
            logger.warning("FTS5 검색 오류: %s", e)
            return []

        if not rows:
            return []

        # MemoryItem 변환 + 감쇠 점수 계산
        results: list[MemorySearchResult] = []
        for row in rows:
            item = self._storage._row_to_item(row)
            fts_score = float(row["fts_score"]) if row["fts_score"] else 0.0

            decay = calc_decay(
                item.type, item.updated_at, item.metadata,
                self._config.half_lives,
            )
            type_weight = self._config.type_priority.get(item.type, 1.0)
            effective_score = fts_score * decay * type_weight

            results.append(MemorySearchResult(
                item=item,
                score=effective_score,
                decay_factor=decay,
            ))

        # 점수 내림차순 정렬
        results.sort(key=lambda r: r.score, reverse=True)

        limit = self._config.search_limit
        rerank_threshold = self._config.rerank_threshold
        needs_rerank = len(results) >= rerank_threshold

        top_results = results[:limit] if not needs_rerank else results

        # accessed_at 갱신 (비동기, 실패 무시)
        for r in top_results[:limit]:
            if r.item.id:
                try:
                    await self._storage.update_accessed(r.item.id)
                except Exception:
                    pass

        return top_results[:limit] if not needs_rerank else results

    def build_context_prompt(
        self,
        results: list[MemorySearchResult],
        char_limit: Optional[int] = None,
    ) -> str:
        """
        검색 결과를 시스템 프롬프트 주입용 문자열로 변환.
        타입별 그룹핑, char_limit 초과 시 낮은 점수부터 제외.
        """
        if not results:
            return ""

        effective_limit = char_limit or self._config.char_limit

        # char_limit 이내로 조정 (낮은 점수부터 제거)
        sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
        included = []
        total_chars = 0
        for r in sorted_results:
            entry = f"- [{r.item.key}] {r.item.content}"
            if total_chars + len(entry) > effective_limit:
                break
            included.append(r)
            total_chars += len(entry)

        if not included:
            return ""

        # 타입별 그룹핑
        type_labels = {
            "profile": "시스템 정보",
            "knowledge": "기술 지식",
            "failure": "과거 실패 경험 (주의)",
            "tool": "사용 가능한 도구",
            "decision": "의사결정 기록",
        }
        groups: dict[str, list[MemorySearchResult]] = {}
        for r in included:
            t = r.item.type
            groups.setdefault(t, []).append(r)

        # failure를 먼저 표시 (안전 우선)
        type_order = ["failure", "tool", "profile", "knowledge", "decision"]
        # 커스텀 타입은 뒤에 추가
        for t in groups:
            if t not in type_order:
                type_order.append(t)

        lines = ["[참고 메모리]"]
        for t in type_order:
            if t not in groups:
                continue
            label = type_labels.get(t, t)
            lines.append(f"### {label}")
            for r in groups[t]:
                lines.append(f"- [{r.item.key}] {r.item.content}")

        lines.append("[참고 메모리 끝]")
        return "\n".join(lines)
