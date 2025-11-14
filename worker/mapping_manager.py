"""Message ID Mapping Manager (DB + Memory Cache)

This module manages the message ID mappings between source and target channels.
It implements a DB-first pattern with memory caching for performance.

Key Features:
- DB-first pattern: All writes go to DB before memory
- Memory cache: Fast lookups without DB queries
- Atomic operations: DB and memory stay in sync
- Crash-safe: Mappings persist across worker restarts
"""

import logging
import aiosqlite
from typing import Dict, Optional, Any

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


class MessageMappingManager:
    """메시지 ID 매핑 관리자 (DB 영구 저장 + 메모리 캐시)

    Purpose:
        - Maps source message IDs to target message IDs
        - Enables edit/delete synchronization in mirroring
        - Persists mappings to DB for crash recovery

    Architecture:
        - DB-first: All modifications hit DB before memory
        - Memory cache: In-memory dict for fast lookups
        - Lazy loading: Loads from DB only when needed

    Attributes:
        worker_id (int): Worker identifier
        worker_name (str): Worker name for logging
        message_map (Dict[int, int]): Source msg ID → Target msg ID cache
    """

    def __init__(self, worker_id: int, worker_name: str):
        """Initialize the mapping manager

        Args:
            worker_id: Unique worker identifier (from DB)
            worker_name: Human-readable worker name (for logging)
        """
        self.worker_id = worker_id
        self.worker_name = worker_name
        self.message_map: Dict[int, int] = {}  # source_msg_id → target_msg_id

    async def save_mapping(
        self,
        source: Any,
        target: Any,
        source_msg_id: int,
        target_msg_id: int
    ):
        """메시지 ID 매핑을 DB에 저장 (DB-first pattern)

        This method saves a message ID mapping to the database and then updates
        the in-memory cache. The DB-first pattern ensures data consistency even
        if the worker crashes.

        Args:
            source: Source chat entity (Channel, Chat, or ID)
            target: Target chat entity (Channel, Chat, or ID)
            source_msg_id: Message ID in source chat
            target_msg_id: Message ID in target chat

        Flow:
            1. Extract chat IDs from entities
            2. Save to DB (INSERT OR REPLACE)
            3. Update memory cache on success
            4. Log errors on failure

        Note:
            - Uses INSERT OR REPLACE for idempotence
            - Memory cache only updated after DB success
            - Errors are logged but not raised (non-critical)
        """
        if not source or not target:
            return

        source_chat_id = str(source.id) if hasattr(source, 'id') else str(source)
        target_chat_id = str(target.id) if hasattr(target, 'id') else str(target)

        try:
            # DB에 먼저 저장 (원자성 보장)
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO message_mappings
                    (worker_id, source_chat_id, target_chat_id, source_msg_id, target_msg_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (self.worker_id, source_chat_id, target_chat_id, source_msg_id, target_msg_id)
                )
                await db.commit()

            # DB 저장 성공 후에만 메모리 캐시 업데이트
            self.message_map[source_msg_id] = target_msg_id

        except Exception as e:
            logger.error(f"매핑 저장 실패 (#{source_msg_id} → #{target_msg_id}): {e}")
            await self.log(f"매핑 저장 실패: {e}", "ERROR")
            # DB 저장 실패 시 메모리에도 저장하지 않음 (일관성 유지)

    async def get_mapping(self, source: Any, source_msg_id: int) -> Optional[int]:
        """메시지 ID 매핑 조회 (메모리 캐시 우선, 없으면 DB)

        This method retrieves the target message ID for a given source message ID.
        It uses a two-tier lookup: memory cache first, then DB if not found.

        Args:
            source: Source chat entity (Channel, Chat, or ID)
            source_msg_id: Message ID in source chat

        Returns:
            Target message ID if mapping exists, None otherwise

        Flow:
            1. Check memory cache first (fast path)
            2. If not found, query DB (slow path)
            3. Cache DB result in memory
            4. Return target message ID or None

        Performance:
            - Cache hit: O(1) dict lookup
            - Cache miss: DB query + cache update

        Note:
            - Automatically populates cache on DB hit
            - Returns None if mapping doesn't exist
            - Errors are logged but not raised
        """
        # 1. 메모리 캐시 확인
        if source_msg_id in self.message_map:
            return self.message_map[source_msg_id]

        # 2. DB에서 조회
        if not source:
            logger.warning(f"⚠️ get_mapping: source is None for msg #{source_msg_id}")
            return None

        source_chat_id = str(source.id) if hasattr(source, 'id') else str(source)

        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    """
                    SELECT target_msg_id FROM message_mappings
                    WHERE worker_id = ? AND source_chat_id = ? AND source_msg_id = ?
                    """,
                    (self.worker_id, source_chat_id, source_msg_id)
                )
                row = await cursor.fetchone()
                if row:
                    target_msg_id = row[0]
                    # 캐시에 추가
                    self.message_map[source_msg_id] = target_msg_id
                    return target_msg_id
        except Exception as e:
            logger.error(f"매핑 조회 실패: {e}")
            await self.log(f"매핑 조회 실패: {e}", "ERROR")

        return None

    async def load_mappings_from_db(self, source: Any):
        """DB에서 기존 매핑을 메모리로 로드 (워커 시작 시)

        This method loads all existing message mappings from the database into
        memory. It should be called when the worker starts to enable edit/delete
        synchronization for previously mirrored messages.

        Args:
            source: Source chat entity (Channel, Chat, or ID)

        Flow:
            1. Extract source chat ID
            2. Query DB for all mappings (latest 10,000)
            3. Load into memory cache
            4. Log count of loaded mappings

        Performance:
            - Loads up to 10,000 most recent mappings
            - Ordered by created_at DESC (newest first)
            - Single DB query for efficiency

        Use Cases:
            - Worker restart: Restore mapping state
            - .미러 command: Load existing mappings before mirroring
            - Crash recovery: Resume with existing mappings

        Note:
            - Limits to 10,000 to avoid memory bloat
            - Only loads mappings for current source chat
            - Errors are logged but not raised
        """
        if not source:
            return

        source_chat_id = str(source.id) if hasattr(source, 'id') else str(source)

        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    """
                    SELECT source_msg_id, target_msg_id FROM message_mappings
                    WHERE worker_id = ? AND source_chat_id = ?
                    ORDER BY created_at DESC
                    LIMIT 10000
                    """,
                    (self.worker_id, source_chat_id)
                )
                rows = await cursor.fetchall()
                for source_id, target_id in rows:
                    self.message_map[source_id] = target_id

                logger.info(f"📝 DB에서 {len(rows)}개 매핑 로드됨")
                await self.log(f"DB에서 {len(rows)}개 매핑 로드됨", "INFO")
        except Exception as e:
            logger.error(f"매핑 로드 실패: {e}")
            await self.log(f"매핑 로드 실패: {e}", "ERROR")

    async def delete_mapping(self, source: Any, source_msg_id: int):
        """메시지 삭제 시 매핑도 제거 (DB-first pattern)

        This method removes a message mapping from both DB and memory when the
        source message is deleted. The DB-first pattern ensures consistency.

        Args:
            source: Source chat entity (Channel, Chat, or ID)
            source_msg_id: Message ID in source chat

        Flow:
            1. Extract source chat ID
            2. Delete from DB first
            3. Remove from memory cache on success
            4. Log errors on failure

        Atomicity:
            - DB deletion happens first
            - Memory only updated after DB success
            - On failure, both DB and memory remain unchanged

        Use Cases:
            - Message deleted in source: Remove mapping
            - Cleanup: Free memory and DB space
            - Consistency: Keep DB and memory in sync

        Note:
            - Safe to call multiple times (idempotent)
            - Errors are logged but not raised
            - Memory only modified after DB success
        """
        if not source:
            logger.warning(f"⚠️ delete_mapping: source is None for msg #{source_msg_id}")
            return

        source_chat_id = str(source.id) if hasattr(source, 'id') else str(source)

        try:
            # DB에서 먼저 삭제 (원자성 보장)
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    """
                    DELETE FROM message_mappings
                    WHERE worker_id = ? AND source_chat_id = ? AND source_msg_id = ?
                    """,
                    (self.worker_id, source_chat_id, source_msg_id)
                )
                await db.commit()

            # DB 삭제 성공 후에만 메모리에서 제거
            if source_msg_id in self.message_map:
                del self.message_map[source_msg_id]

        except Exception as e:
            logger.error(f"매핑 삭제 실패 (#{source_msg_id}): {e}")
            await self.log(f"매핑 삭제 실패: {e}", "ERROR")
            # DB 삭제 실패 시 메모리도 건드리지 않음 (일관성 유지)

    async def log(self, message: str, level: str = "INFO"):
        """로그를 DB에 저장

        This method saves a log entry to the database for centralized logging.
        The Manager Bot will later deliver these logs to configured channels.

        Args:
            message: Log message text
            level: Log level (INFO, WARNING, ERROR, SUCCESS, START, STOP)

        Log Levels:
            - INFO: General information
            - WARNING: Non-critical issues
            - ERROR: Critical failures
            - SUCCESS: Successful operations
            - START: Worker started
            - STOP: Worker stopped

        Flow:
            1. Insert log entry into DB
            2. Commit transaction
            3. Log errors to stderr on failure

        Note:
            - Errors are logged to stderr but not raised
            - Log delivery happens asynchronously via Manager Bot
            - sent=0 flag indicates not yet delivered
        """
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    """INSERT INTO logs (worker_id, worker_name, level, message)
                       VALUES (?, ?, ?, ?)""",
                    (self.worker_id, self.worker_name, level, message)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"로그 저장 실패: {e}")

    def clear_cache(self):
        """메모리 캐시 초기화

        This method clears the in-memory message mapping cache. It should be
        called when switching to a different source chat.

        Use Cases:
            - Source chat changed: Clear old mappings
            - Memory cleanup: Free unused memory
            - Testing: Reset state

        Note:
            - Does NOT affect DB
            - Only clears memory cache
            - Can be repopulated via load_mappings_from_db()
        """
        self.message_map.clear()
        logger.info("메모리 캐시 초기화됨")

    def get_cache_size(self) -> int:
        """메모리 캐시 크기 조회

        Returns:
            Number of mappings currently cached in memory

        Use Cases:
            - Monitoring: Check memory usage
            - Debugging: Verify cache population
            - Statistics: Report mapping count
        """
        return len(self.message_map)
