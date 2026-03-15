"""
메모리 정비 시스템.
새벽 정기 정비: 시간 감쇠로 만료된 메모리 소프트 삭제 + VACUUM.

의존성 분리 (원본 대비 변경사항):
    - settings → MemoryConfig
    - search.HALF_LIVES → config.half_lives
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite

from .config import MemoryConfig
from .search import calc_decay
from .storage import MemoryStorage

logger = logging.getLogger(__name__)


class MemoryMaintenance:
    """메모리 정기 정비 실행기."""

    def __init__(self, storage: MemoryStorage, config: MemoryConfig):
        self._storage = storage
        self._config = config
        self._schedule_task: asyncio.Task | None = None

    async def run_daily(self) -> dict:
        """
        새벽 정비 진입점.
        1. 감쇠 점수 threshold 이하 레코드 soft delete (critical failure 제외)
        2. VACUUM 실행
        3. 완료 타임스탬프 기록
        """
        logger.info("메모리 일일 정비 시작")
        start = datetime.now(timezone.utc)
        deactivated_count = 0

        # 1) 감쇠된 레코드 소프트 삭제
        try:
            # 감쇠 가능한 타입 결정 (반감기가 있는 타입만)
            decay_types = [
                t for t, hl in self._config.half_lives.items()
                if hl is not None
            ]

            if decay_types:
                async with aiosqlite.connect(self._storage._db_path) as conn:
                    await conn.execute("PRAGMA journal_mode=WAL")
                    conn.row_factory = aiosqlite.Row

                    placeholders = ",".join("?" * len(decay_types))
                    cursor = await conn.execute(
                        f"""SELECT id, type, updated_at, metadata
                           FROM memories
                           WHERE is_active=1
                             AND type IN ({placeholders})""",
                        decay_types,
                    )
                    rows = await cursor.fetchall()

                # 소프트 삭제 대상 선별
                to_deactivate = []
                for row in rows:
                    mem_type = row["type"]
                    updated_at_str = row["updated_at"]
                    metadata_str = row["metadata"] or "{}"

                    try:
                        metadata = json.loads(metadata_str)
                    except Exception:
                        metadata = {}

                    updated_at = None
                    if updated_at_str:
                        try:
                            updated_at = datetime.fromisoformat(updated_at_str)
                        except Exception:
                            pass

                    decay = calc_decay(
                        mem_type, updated_at, metadata,
                        self._config.half_lives,
                    )
                    if decay <= self._config.decay_threshold:
                        to_deactivate.append(row["id"])

                # 배치 소프트 삭제
                if to_deactivate:
                    async with self._storage._write_lock:
                        async with aiosqlite.connect(self._storage._db_path) as conn:
                            await conn.execute("PRAGMA journal_mode=WAL")
                            placeholders = ",".join("?" * len(to_deactivate))
                            await conn.execute(
                                f"UPDATE memories SET is_active=0, updated_at=datetime('now') "
                                f"WHERE id IN ({placeholders})",
                                to_deactivate,
                            )
                            await conn.commit()
                    deactivated_count = len(to_deactivate)
                    logger.info("정비: %d개 레코드 소프트 삭제 (decay <= %.2f)",
                                deactivated_count, self._config.decay_threshold)

        except Exception as e:
            logger.error("정비 중 감쇠 처리 오류: %s", e, exc_info=True)

        # 2) VACUUM (write_lock 획득 후)
        try:
            async with self._storage._write_lock:
                async with aiosqlite.connect(self._storage._db_path) as conn:
                    await conn.execute("VACUUM")
                    await conn.commit()
            logger.info("VACUUM 완료")
        except Exception as e:
            logger.error("VACUUM 오류: %s", e, exc_info=True)

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info("메모리 일일 정비 완료: deactivated=%d, duration=%.2fs",
                    deactivated_count, duration)

        return {
            "deactivated": deactivated_count,
            "duration_seconds": duration,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def schedule(self, hour: Optional[int] = None) -> None:
        """매일 지정 시각(hour)에 run_daily()를 실행하는 asyncio 스케줄러."""
        effective_hour = hour if hour is not None else self._config.maintenance_hour

        async def _loop():
            logger.info("메모리 정비 스케줄러 시작 (매일 %d시)", effective_hour)
            while True:
                try:
                    now = datetime.now(timezone.utc)
                    kst_offset = timedelta(hours=9)
                    now_kst = now + kst_offset
                    next_run_kst = now_kst.replace(
                        hour=effective_hour, minute=0, second=0, microsecond=0
                    )
                    if next_run_kst <= now_kst:
                        next_run_kst += timedelta(days=1)
                    wait_seconds = (next_run_kst - now_kst).total_seconds()
                    logger.info("다음 메모리 정비까지 %.0f초 대기", wait_seconds)
                    await asyncio.sleep(wait_seconds)
                    await self.run_daily()
                except asyncio.CancelledError:
                    logger.info("메모리 정비 스케줄러 종료")
                    break
                except Exception as e:
                    logger.error("메모리 정비 스케줄러 오류: %s", e, exc_info=True)
                    await asyncio.sleep(3600)

        self._schedule_task = asyncio.create_task(_loop())

    async def stop(self) -> None:
        """스케줄러 종료."""
        if self._schedule_task and not self._schedule_task.done():
            self._schedule_task.cancel()
            try:
                await self._schedule_task
            except asyncio.CancelledError:
                pass


# typing import for Optional
from typing import Optional
