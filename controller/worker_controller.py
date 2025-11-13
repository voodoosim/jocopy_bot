"""Worker Controller - 워커 프로세스 관리"""
import asyncio
import logging
import multiprocessing as mp
from typing import Dict, Optional
import aiosqlite

from config import (
    MAX_ACTIVE_WORKERS,
    MAX_CONCURRENT_TASKS,
    WORKER_IDLE_TIMEOUT_SEC,
    DATABASE_PATH
)
from worker import WorkerBot

logger = logging.getLogger(__name__)


class WorkerController:
    """워커 프로세스 관리자"""

    def __init__(self):
        # 활성 워커 프로세스 {worker_id: Process}
        self.active_workers: Dict[int, mp.Process] = {}

        # 작업 중인 워커 수
        self.working_count = 0

        # 컨트롤러 실행 상태
        self.running = False

    async def start_worker(self, worker_id: int) -> bool:
        """
        워커 시작

        Args:
            worker_id: 워커 ID (DB)

        Returns:
            성공 여부
        """
        # 이미 실행 중인지 확인
        if worker_id in self.active_workers:
            if self.active_workers[worker_id].is_alive():
                logger.warning(f"Worker {worker_id} 이미 실행 중")
                return False

        # 최대 활성 워커 수 확인
        active_count = sum(
            1 for p in self.active_workers.values() if p.is_alive()
        )

        if active_count >= MAX_ACTIVE_WORKERS:
            logger.warning(
                f"최대 활성 워커 수 도달: {active_count}/{MAX_ACTIVE_WORKERS}"
            )
            return False

        # DB에서 워커 정보 가져오기
        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT name, session_string FROM workers WHERE id = ?",
                (worker_id,)
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            logger.error(f"Worker {worker_id} 찾을 수 없음")
            return False

        worker_name, session_string = row

        # 워커 프로세스 생성
        process = mp.Process(
            target=self._run_worker_process,
            args=(worker_id, worker_name, session_string),
            name=f"Worker-{worker_name}",
            daemon=True
        )

        process.start()
        self.active_workers[worker_id] = process

        logger.info(f"✅ Worker {worker_id} ({worker_name}) 시작: PID {process.pid}")

        # DB 상태 업데이트
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                UPDATE workers
                SET process_id = ?, status = 'starting'
                WHERE id = ?
                """,
                (process.pid, worker_id)
            )
            await db.commit()

        return True

    async def stop_worker(self, worker_id: int) -> bool:
        """
        워커 중지

        Args:
            worker_id: 워커 ID

        Returns:
            성공 여부
        """
        if worker_id not in self.active_workers:
            logger.warning(f"Worker {worker_id} 실행 중 아님")
            return False

        process = self.active_workers[worker_id]

        if not process.is_alive():
            logger.warning(f"Worker {worker_id} 이미 종료됨")
            del self.active_workers[worker_id]
            return False

        # 프로세스 종료
        logger.info(f"🛑 Worker {worker_id} 중지 중...")
        process.terminate()

        # 최대 5초 대기
        process.join(timeout=5)

        if process.is_alive():
            logger.warning(f"Worker {worker_id} 강제 종료")
            process.kill()
            process.join()

        del self.active_workers[worker_id]

        # DB 상태 업데이트
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                UPDATE workers
                SET process_id = NULL, status = 'stopped'
                WHERE id = ?
                """,
                (worker_id,)
            )
            await db.commit()

        logger.info(f"✅ Worker {worker_id} 중지 완료")
        return True

    async def restart_worker(self, worker_id: int) -> bool:
        """
        워커 재시작

        Args:
            worker_id: 워커 ID

        Returns:
            성공 여부
        """
        logger.info(f"🔄 Worker {worker_id} 재시작 중...")

        # 중지
        if worker_id in self.active_workers:
            await self.stop_worker(worker_id)
            await asyncio.sleep(1)

        # 시작
        return await self.start_worker(worker_id)

    async def cleanup_dead_workers(self):
        """종료된 워커 프로세스 정리"""
        dead_workers = [
            worker_id
            for worker_id, process in self.active_workers.items()
            if not process.is_alive()
        ]

        for worker_id in dead_workers:
            logger.warning(f"⚠️ Worker {worker_id} 비정상 종료 감지")
            del self.active_workers[worker_id]

            # DB 상태 업데이트
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    """
                    UPDATE workers
                    SET process_id = NULL, status = 'crashed'
                    WHERE id = ?
                    """,
                    (worker_id,)
                )
                await db.commit()

    async def get_worker_status(self, worker_id: int) -> Optional[str]:
        """
        워커 상태 조회

        Args:
            worker_id: 워커 ID

        Returns:
            상태 문자열 (running/stopped/crashed)
        """
        if worker_id in self.active_workers:
            if self.active_workers[worker_id].is_alive():
                return "running"
            else:
                return "crashed"

        # DB에서 확인
        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT status FROM workers WHERE id = ?",
                (worker_id,)
            ) as cursor:
                row = await cursor.fetchone()

        return row[0] if row else None

    async def monitor_loop(self):
        """워커 모니터링 루프"""
        self.running = True
        logger.info("🔍 워커 모니터링 시작")

        while self.running:
            try:
                # 종료된 워커 정리
                await self.cleanup_dead_workers()

                # 30초 대기
                await asyncio.sleep(30)

            except Exception as e:
                logger.error(f"모니터링 중 오류: {e}", exc_info=True)
                await asyncio.sleep(5)

        logger.info("🛑 워커 모니터링 종료")

    async def shutdown(self):
        """모든 워커 종료"""
        self.running = False
        logger.info("🛑 모든 워커 종료 중...")

        # 모든 워커 중지
        worker_ids = list(self.active_workers.keys())
        for worker_id in worker_ids:
            await self.stop_worker(worker_id)

        logger.info("✅ 모든 워커 종료 완료")

    @staticmethod
    def _run_worker_process(
        worker_id: int,
        worker_name: str,
        session_string: str
    ):
        """
        워커 프로세스 진입점 (별도 프로세스에서 실행)

        Args:
            worker_id: 워커 ID
            worker_name: 워커 이름
            session_string: Telethon 세션 문자열
        """
        # 로깅 설정 (자식 프로세스)
        logging.basicConfig(
            level=logging.INFO,
            format=f'%(asctime)s - Worker-{worker_name} - %(levelname)s - %(message)s'
        )

        logger = logging.getLogger(__name__)
        logger.info(f"🚀 Worker 프로세스 시작: {worker_name}")

        try:
            # WorkerBot 생성 및 실행
            worker = WorkerBot(worker_id, worker_name, session_string)
            asyncio.run(worker.start())

        except KeyboardInterrupt:
            logger.info(f"👋 Worker {worker_name} 종료 (Ctrl+C)")
        except Exception as e:
            logger.error(f"Worker {worker_name} 오류: {e}", exc_info=True)
        finally:
            logger.info(f"✅ Worker {worker_name} 프로세스 종료")
