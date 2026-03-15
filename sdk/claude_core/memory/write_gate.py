"""
Write Gate: 메모리 저장 판단 시스템.
Stage 1: 규칙 기반 빠른 필터 (<1ms)
Stage 2: Claude(Haiku) 분류 (비동기, ~1-3초)

의존성 분리 (원본 대비 변경사항):
    - 모듈 레벨 상수 → MemoryConfig에서 주입
    - STAGE2_PROMPT → config.stage2_prompt로 커스터마이징 가능
"""
import asyncio
import json
import logging
from typing import Callable, Optional

from .config import MemoryConfig
from .models import MemorySaveRequest, MemoryType, WriteGateResult

logger = logging.getLogger(__name__)

# Stage 2: 기본 Claude 분류 프롬프트
_DEFAULT_STAGE2_PROMPT = """다음 대화를 분석하여 메모리 저장 여부를 판단하세요.

[대화]
{conversation}

저장할 정보가 있으면 다음 JSON 형식으로만 응답하세요:
{{
  "should_save": true,
  "memories": [
    {{
      "type": "profile|knowledge|failure|tool|decision",
      "key": "짧은 식별 키 (한글 또는 영소문자, 하이픈으로 단어 구분, 예: 젠킨스-연동-설정)",
      "content": "핵심 내용 (1-3문장)",
      "tags": ["태그1", "태그2"],
      "confidence": 0.0~1.0
    }}
  ]
}}

저장할 정보가 없으면:
{{"should_save": false, "memories": []}}

메모리 타입 가이드:
- profile: 서버 정보, 프로젝트 구조 등 영구적 사실
- knowledge: 기술 지식, 설정 방법, 해결책
- failure: 오류, 실패 패턴, 주의사항
- tool: 만든 스크립트나 도구
- decision: 의사결정 근거, 선택한 이유

confidence >= 0.7인 항목만 실제 저장됩니다."""


def stage1_check(
    message: str,
    response: str,
    context: dict,
    config: MemoryConfig,
) -> str:
    """
    Stage 1 규칙 기반 필터.

    Returns:
        "force_save": 명시적 저장 요청 -> Stage2 건너뛰고 바로 저장
        "skip": 저장 불필요 (인사말, 짧은 메시지)
        "promote": Stage2 진입 권장 (오류, 도구 사용, 긴 응답 등)
        "pass": 그 외 (Stage2 진입 안 함)
    """
    msg_lower = message.lower().strip()
    resp_lower = response.lower().strip()

    # 1) 강제 저장 트리거
    for trigger in config.force_save_triggers:
        if trigger in msg_lower or trigger in resp_lower:
            logger.debug("Stage1: force_save (trigger=%s)", trigger)
            return "force_save"

    # 2) 스킵: 너무 짧음
    if len(message.strip()) < config.min_message_length:
        return "skip"

    # 3) 스킵: 인사말
    for greeting in config.skip_greetings:
        if msg_lower.startswith(greeting):
            return "skip"

    # 4) 그 외 전부 Stage2 진입
    logger.debug("Stage1: promote (default)")
    return "promote"


def parse_stage2_result(raw_json: str, config: MemoryConfig) -> WriteGateResult:
    """Stage 2 Claude 응답 JSON 파싱. 실패 시 should_save=False."""
    try:
        import re
        text = raw_json.strip()
        if "```" in text:
            match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
            if match:
                text = match.group(1).strip()

        data = json.loads(text)
        should_save = bool(data.get("should_save", False))
        memories_raw = data.get("memories", [])

        memories = []
        for m in memories_raw:
            confidence = float(m.get("confidence", 0.0))
            if confidence < config.confidence_threshold:
                continue

            mem_type_str = m.get("type", "knowledge")
            # 기본 타입이면 enum으로, 커스텀이면 문자열 그대로
            mem_type = MemoryType.from_str(mem_type_str)
            type_value = mem_type.value if isinstance(mem_type, MemoryType) else mem_type

            memories.append(MemorySaveRequest(
                type=type_value,
                key=m.get("key", "unknown"),
                content=m.get("content", ""),
                tags=m.get("tags", []),
                confidence=confidence,
                metadata={},
            ))

        return WriteGateResult(should_save=should_save and bool(memories), memories=memories)

    except Exception as e:
        logger.warning("Stage2 JSON 파싱 실패 (should_save=False): %s", e)
        return WriteGateResult(should_save=False, memories=[])


class WriteGate:
    """Write Gate: 2단계 메모리 저장 판단."""

    def __init__(
        self,
        claude_callable: Optional[Callable] = None,
        queue_size: int = 10,
        storage=None,  # MemoryStorage (순환 임포트 방지용 Any)
        config: Optional[MemoryConfig] = None,
    ):
        """
        Args:
            claude_callable: Claude 호출 함수 (async, prompt str -> str 반환)
                             None이면 Stage2 비활성화
            queue_size: Stage2 큐 최대 크기 (초과 시 oldest drop)
            storage: MemoryStorage 인스턴스. 있으면 큐를 DB에 영속화하여 재시작 복원
            config: MemoryConfig. None이면 기본값 사용
        """
        self._claude_callable = claude_callable
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._queue_size = queue_size
        self._processing_task: Optional[asyncio.Task] = None
        self._storage = storage
        self._config = config or MemoryConfig()

    @property
    def config(self) -> MemoryConfig:
        return self._config

    def start(self) -> None:
        """Stage2 백그라운드 처리 루프 시작."""
        if self._processing_task is None or self._processing_task.done():
            self._processing_task = asyncio.create_task(self._start_with_restore())
            logger.info("WriteGate Stage2 처리 루프 시작")

    async def _start_with_restore(self) -> None:
        """DB에 남아있는 미처리 항목을 큐에 복원한 뒤 처리 루프 실행."""
        if self._storage:
            try:
                pending = await self._storage.get_pending_analyses()
                if pending:
                    logger.info("WriteGate: 미처리 항목 %d건 복원", len(pending))
                    for p in pending:
                        storage_ref = self._storage
                        user_id_ref = p["user_id"]

                        async def _default_on_save(
                            memories: list,
                            uid: str,
                            _storage=storage_ref,
                        ) -> None:
                            for mem_req in memories:
                                mem_req.author = uid
                                try:
                                    await _storage.save(mem_req, author=uid)
                                    logger.info(
                                        "WriteGate 복원 항목 저장 완료: type=%s, key=%s",
                                        mem_req.type if isinstance(mem_req.type, str) else mem_req.type.value,
                                        mem_req.key,
                                    )
                                except Exception as e:
                                    logger.warning("WriteGate 복원 항목 저장 오류: %s", e)

                        item = {
                            "conversation": p["conversation"],
                            "user_id": user_id_ref,
                            "on_save": _default_on_save,
                            "pending_id": p["id"],
                        }
                        try:
                            self._queue.put_nowait(item)
                        except asyncio.QueueFull:
                            break
            except Exception as e:
                logger.warning("WriteGate 큐 복원 오류 (무시): %s", e)
        await self._process_loop()

    async def stop(self) -> None:
        """Stage2 처리 루프 종료."""
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass

    async def enqueue(
        self,
        conversation: str,
        user_id: str,
        on_save: Optional[Callable] = None,
    ) -> None:
        """Stage2 분류 큐에 추가."""
        pending_id = None
        if self._storage:
            try:
                pending_id = await self._storage.add_pending_analysis(conversation, user_id)
            except Exception as e:
                logger.warning("WriteGate DB 저장 오류 (무시): %s", e)

        item = {
            "conversation": conversation,
            "user_id": user_id,
            "on_save": on_save,
            "pending_id": pending_id,
        }

        if self._queue.full():
            try:
                dropped = self._queue.get_nowait()
                logger.warning("WriteGate 큐 포화, oldest drop: user_id=%s",
                               dropped.get("user_id", "?"))
                if self._storage and dropped.get("pending_id"):
                    try:
                        await self._storage.delete_pending_analysis(dropped["pending_id"])
                    except Exception:
                        pass
            except asyncio.QueueEmpty:
                pass

        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.warning("WriteGate 큐 full, 항목 버림: user_id=%s", user_id)
            if self._storage and pending_id:
                try:
                    await self._storage.delete_pending_analysis(pending_id)
                except Exception:
                    pass

    async def stage2_classify(self, conversation: str) -> WriteGateResult:
        """Stage 2: Claude Haiku로 대화 분류."""
        if not self._claude_callable:
            return WriteGateResult(should_save=False, memories=[])

        prompt_template = self._config.stage2_prompt or _DEFAULT_STAGE2_PROMPT
        prompt = prompt_template.format(conversation=conversation[:3000])
        try:
            raw = await self._claude_callable(prompt)
            return parse_stage2_result(raw, self._config)
        except Exception as e:
            logger.warning("Stage2 Claude 호출 실패 (best-effort, 무시): %s", e)
            return WriteGateResult(should_save=False, memories=[])

    async def _process_loop(self) -> None:
        """Stage2 큐에서 순차 처리하는 백그라운드 루프."""
        logger.info("WriteGate 처리 루프 실행 중")
        while True:
            try:
                item = await self._queue.get()
                conversation = item.get("conversation", "")
                user_id = item.get("user_id", "")
                on_save = item.get("on_save")
                pending_id = item.get("pending_id")

                result = await self.stage2_classify(conversation)

                if result.should_save and on_save:
                    try:
                        await on_save(result.memories, user_id)
                    except Exception as e:
                        logger.warning("WriteGate on_save 콜백 오류: %s", e)

                # 처리 완료 -> DB에서 삭제
                if self._storage and pending_id:
                    try:
                        await self._storage.delete_pending_analysis(pending_id)
                    except Exception:
                        pass

                self._queue.task_done()

            except asyncio.CancelledError:
                logger.info("WriteGate 처리 루프 종료")
                break
            except Exception as e:
                logger.error("WriteGate 처리 루프 오류: %s", e, exc_info=True)
