"""
메모리 서비스 파사드.
저장소, 검색, Write Gate를 통합하는 단일 진입점.

의존성 분리 (원본 대비 변경사항):
    - settings → MemoryConfig
    - 싱글톤 (get_memory_service, initialize_memory_service) 제거
    - create() 팩토리 메서드 추가
"""
import json
import logging
import re
from typing import Callable, Optional

from .config import MemoryConfig
from .models import MemoryItem, MemorySaveRequest, MemorySearchResult, MemoryType
from .search import MemorySearcher
from .storage import MemoryStorage
from .write_gate import WriteGate, stage1_check

logger = logging.getLogger(__name__)


class MemoryService:
    """
    메모리 시스템 통합 파사드.

    storage, searcher, write_gate를 통합하고
    외부에서 단일 인터페이스로 메모리 시스템을 사용할 수 있게 한다.
    """

    def __init__(
        self,
        storage: MemoryStorage,
        searcher: MemorySearcher,
        write_gate: WriteGate,
        claude_callable: Optional[Callable] = None,
        config: Optional[MemoryConfig] = None,
    ):
        """
        Args:
            storage: SQLite 저장소
            searcher: FTS5 검색기
            write_gate: Write Gate 판단기
            claude_callable: claude-memory 데몬 호출 함수 (DI)
                async (prompt: str) -> str
            config: MemoryConfig 설정
        """
        self._storage = storage
        self._searcher = searcher
        self._write_gate = write_gate
        self._claude_callable = claude_callable
        self._config = config or MemoryConfig()

    @classmethod
    async def create(
        cls,
        config: MemoryConfig,
        claude_callable: Optional[Callable] = None,
    ) -> "MemoryService":
        """
        MemoryService 팩토리. 내부적으로 Storage/Searcher/WriteGate를 생성한다.

        Args:
            config: MemoryConfig 설정
            claude_callable: async (prompt: str) -> str
                            Write Gate Stage2 + 재랭킹에 사용
                            None이면 Stage2 비활성, FTS5만으로 동작

        Returns:
            초기화 완료된 MemoryService 인스턴스
        """
        config.validate()

        storage = MemoryStorage(config)
        await storage.initialize()

        searcher = MemorySearcher(storage, config)
        write_gate = WriteGate(
            claude_callable=claude_callable,
            storage=storage,
            config=config,
        )
        write_gate.start()

        return cls(
            storage=storage,
            searcher=searcher,
            write_gate=write_gate,
            claude_callable=claude_callable,
            config=config,
        )

    async def build_context_prompt(self, query: str, user_id: str = "") -> str:
        """
        쿼리에 관련된 메모리를 검색하여 시스템 프롬프트 주입용 문자열을 반환한다.
        """
        try:
            results = await self._searcher.search(query)

            # Claude 재랭킹 (결과 >= rerank_threshold + callable 있을 때)
            if len(results) >= self._config.rerank_threshold and self._claude_callable:
                results = await self._rerank_with_claude(query, results)

            return self._searcher.build_context_prompt(results, self._config.char_limit)

        except Exception as e:
            logger.warning("메모리 컨텍스트 빌드 오류 (무시): %s", e)
            return ""

    async def _rerank_with_claude(
        self,
        query: str,
        results: list[MemorySearchResult],
    ) -> list[MemorySearchResult]:
        """Claude Haiku로 검색 결과 재랭킹."""
        if not self._claude_callable:
            return results

        items_text = "\n".join(
            f"{i+1}. [{r.item.type}] {r.item.key}: {r.item.content[:200]}"
            for i, r in enumerate(results)
        )
        prompt = (
            f"다음 메모리 항목들을 '{query}' 쿼리와의 관련성 순으로 재정렬하세요.\n"
            f"가장 관련 있는 순서대로 번호만 JSON 배열로 반환하세요. 예: [3,1,4,2]\n\n"
            f"{items_text}"
        )

        try:
            raw = await self._claude_callable(prompt)
            match = re.search(r"\[[\d,\s]+\]", raw)
            if match:
                order = json.loads(match.group())
                reranked = []
                seen = set()
                for idx in order:
                    i = idx - 1
                    if 0 <= i < len(results) and i not in seen:
                        reranked.append(results[i])
                        seen.add(i)
                for i, r in enumerate(results):
                    if i not in seen:
                        reranked.append(r)
                return reranked
        except Exception as e:
            logger.warning("재랭킹 파싱 오류, 원본 순서 유지: %s", e)

        return results

    async def pre_action_check(self, tool_name: str) -> dict:
        """도구 실행 전 failure 이력을 확인한다."""
        try:
            results = await self._searcher.search(
                tool_name, type_filter="failure"
            )
            if not results:
                return {"has_failures": False, "warnings": [], "should_confirm": False}

            warnings = []
            should_confirm = False
            for r in results:
                item = r.item
                meta = item.metadata
                severity = meta.get("severity", "low")
                resolution = meta.get("resolution", {})

                warning = f"[{severity.upper()}] {item.key}: {item.content}"
                if resolution.get("solution"):
                    warning += f" -> 해결: {resolution['solution']}"
                warnings.append(warning)

                if severity in ("critical", "high"):
                    should_confirm = True

            return {
                "has_failures": True,
                "warnings": warnings,
                "should_confirm": should_confirm,
            }
        except Exception as e:
            logger.warning("pre_action_check 오류 (무시): %s", e)
            return {"has_failures": False, "warnings": [], "should_confirm": False}

    async def post_conversation(
        self,
        message: str,
        response: str,
        user_id: str,
        context: Optional[dict] = None,
    ) -> None:
        """대화 완료 후 메모리 저장 판단 및 처리."""
        if not self._config.write_gate_enabled:
            return

        ctx = context or {}

        try:
            stage1_result = stage1_check(message, response, ctx, self._config)
            logger.debug("WriteGate Stage1 결과: %s (user_id=%s)", stage1_result, user_id)

            if stage1_result == "force_save":
                req = MemorySaveRequest(
                    type=MemoryType.KNOWLEDGE.value,
                    key=f"manual-{user_id}-{message[:30].replace(' ', '-')}",
                    content=f"[{user_id}의 저장 요청] {message[:200]}",
                    tags=["manual", user_id],
                    confidence=1.0,
                    author=user_id,
                    source_conversation=f"Q: {message[:200]}\nA: {response[:200]}",
                )
                await self._storage.save(req, author=user_id)
                logger.info("WriteGate force_save 완료: user_id=%s", user_id)

            elif stage1_result == "promote":
                logger.info("WriteGate promote: Stage2 큐에 추가 중 (user_id=%s)", user_id)
                conversation = f"사용자: {message}\n\n어시스턴트: {response}"

                async def _on_save(memories: list[MemorySaveRequest], uid: str) -> None:
                    for mem_req in memories:
                        mem_req.author = uid
                        try:
                            await self._storage.save(mem_req, author=uid)
                            logger.info("WriteGate Stage2 저장 완료: type=%s, key=%s",
                                       mem_req.type, mem_req.key)
                        except Exception as e:
                            logger.warning("WriteGate Stage2 저장 오류: %s", e)

                await self._write_gate.enqueue(conversation, user_id, on_save=_on_save)

        except Exception as e:
            logger.warning("post_conversation 오류 (best-effort, 무시): %s", e)

    async def search(
        self,
        query: str,
        type_filter: Optional[str] = None,
    ) -> list[MemorySearchResult]:
        """메모리 검색."""
        return await self._searcher.search(query, type_filter=type_filter)

    async def save(self, request: MemorySaveRequest, author: str = "") -> MemoryItem:
        """메모리 직접 저장."""
        return await self._storage.save(request, author=author)

    async def get_stats(self) -> dict:
        """메모리 통계."""
        return await self._storage.get_stats()

    async def shutdown(self) -> None:
        """메모리 서비스 종료."""
        await self._write_gate.stop()
        await self._storage.close()
        logger.info("메모리 서비스 종료 완료")
