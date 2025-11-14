"""Permanent Event Handlers for Real-Time Mirroring

This module contains the permanent event handlers that are registered once
and controlled by the mirroring_active flag. These handlers enable real-time
message synchronization between source and target chats.

Architecture:
- Dependency injection pattern for maximum decoupling
- State-based activation (mirroring_active flag)
- DB-persisted message ID mappings for edit/delete sync
- FloodWait automatic retry logic
- Album support with safe zip handling
"""
import logging
import asyncio
from typing import Callable, Optional
from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    MessageIdInvalidError,
    ChatWriteForbiddenError,
    ChannelPrivateError
)

logger = logging.getLogger(__name__)


class PermanentEventHandlers:
    """영구 이벤트 핸들러 (실시간 미러링)

    Features:
    - NewMessage: Forward individual messages
    - Album: Forward media groups
    - MessageDeleted: Sync deletions
    - MessageEdited: Sync text edits

    All handlers respect the mirroring_active flag and only process messages
    from the configured source chat.
    """

    def __init__(
        self,
        client: TelegramClient,
        log_callback: Callable[[str, str], None],
        get_mirroring_active: Callable[[], bool],
        get_source: Callable[[], Optional[object]],
        get_target: Callable[[], Optional[object]],
        get_topic_mapping: Callable[[], dict],
        save_mapping: Callable[[int, int], None],
        get_mapping: Callable[[int], Optional[int]],
        delete_mapping: Callable[[int], None],
    ):
        """Initialize permanent event handlers with dependencies.

        Args:
            client: Telethon TelegramClient instance
            log_callback: async function(message: str, level: str)
            get_mirroring_active: lambda returning bool
            get_source: lambda returning source entity
            get_target: lambda returning target entity
            get_topic_mapping: lambda returning topic_mapping dict
            save_mapping: async function(source_id: int, target_id: int)
            get_mapping: async function(source_id: int) -> Optional[int]
            delete_mapping: async function(source_id: int)
        """
        self.client = client
        self.log = log_callback
        self.get_mirroring_active = get_mirroring_active
        self.get_source = get_source
        self.get_target = get_target
        self.get_topic_mapping = get_topic_mapping
        self.save_mapping = save_mapping
        self.get_mapping = get_mapping
        self.delete_mapping = delete_mapping

    def register_handlers(self):
        """Register all permanent event handlers.

        This should be called once during WorkerBot initialization.
        The handlers are controlled by the mirroring_active flag.
        """
        self._register_new_message_handler()
        self._register_album_handler()
        self._register_deleted_handler()
        self._register_edited_handler()

    def _register_new_message_handler(self):
        """Register NewMessage handler for individual messages."""

        @self.client.on(events.NewMessage())
        async def on_new_permanent(e):
            """영구 NewMessage 핸들러 (중복 등록 방지)"""
            # 미러링 비활성 또는 소스 불일치 시 무시
            if not self.get_mirroring_active():
                return

            source = self.get_source()
            target = self.get_target()

            if not source or not target or e.chat_id != source.id:
                return

            # Album 메시지는 on_album에서 처리
            if e.message.grouped_id:
                return

            try:
                # 토픽 ID 확인 (Forum)
                topic_id = getattr(e.message, 'message_thread_id', None)
                topic_mapping = self.get_topic_mapping()
                target_topic_id = topic_mapping.get(topic_id) if topic_id else None

                if target_topic_id:
                    logger.info(f"토픽 메시지 복사: #{e.message.id} → 토픽 #{target_topic_id}")

                # MCP 방식으로 전송
                result = await self.client.forward_messages(
                    target,
                    e.message.id,
                    source,
                    drop_author=True
                )

                # 메시지 ID 매핑 저장 (편집/삭제 동기화용) - DB에 영구 저장
                if result:
                    if hasattr(result, 'id'):
                        target_id = result.id
                    elif isinstance(result, list) and result:
                        target_id = result[0].id
                    else:
                        logger.warning("⚠️ forward_messages returned unexpected type")
                        target_id = None

                    if target_id:
                        await self.save_mapping(e.message.id, target_id)
                        logger.debug(f"📝 매핑 저장: {e.message.id} → {target_id}")

            except FloodWaitError as fw:
                logger.warning(f"⏰ FloodWait {fw.seconds}초 대기")
                await asyncio.sleep(fw.seconds)
                try:
                    result = await self.client.forward_messages(
                        target, e.message.id, source, drop_author=True
                    )
                    # FloodWait 재시도 후에도 매핑 저장
                    if result:
                        if hasattr(result, 'id'):
                            target_id = result.id
                        elif isinstance(result, list) and result:
                            target_id = result[0].id
                        else:
                            logger.warning("⚠️ 재시도 후 예상치 못한 타입")
                            target_id = None

                        if target_id:
                            await self.save_mapping(e.message.id, target_id)
                except Exception as retry_ex:
                    logger.error(f"❌ FloodWait 재시도 실패: {retry_ex}")

            except MessageIdInvalidError:
                logger.warning(f"⚠️ 메시지 #{e.message.id} 건너뜀")
            except ChatWriteForbiddenError:
                logger.error("❌ 타겟 채널 쓰기 권한 없음!")
            except ChannelPrivateError:
                logger.error("❌ 소스 채널 접근 권한 없음!")

    def _register_album_handler(self):
        """Register Album handler for media groups."""

        @self.client.on(events.Album())
        async def on_album_permanent(e):
            """영구 Album 핸들러 (중복 등록 방지)"""
            if not self.get_mirroring_active():
                return

            source = self.get_source()
            target = self.get_target()

            if not source or not target or e.chat_id != source.id:
                return

            try:
                # MCP 방식으로 Album 전송
                source_ids = [m.id for m in e.messages]
                result = await self.client.forward_messages(
                    target,
                    source_ids,
                    source,
                    drop_author=True
                )

                # 메시지 ID 매핑 저장 (Album의 각 메시지) - DB에 영구 저장
                # Bug #1 수정: zip 안전성 체크
                if result:
                    target_messages = result if isinstance(result, list) else [result]

                    # 크기 불일치 경고 (Bug #1)
                    if len(e.messages) != len(target_messages):
                        logger.warning(
                            f"⚠️ Album 크기 불일치: 전송 {len(e.messages)}개, "
                            f"수신 {len(target_messages)}개 (grouped_id={e.grouped_id})"
                        )
                        await self.log(f"Album 부분 전송: {len(target_messages)}/{len(e.messages)}", "WARNING")

                    # 안전하게 최소 길이만큼만 매핑
                    min_len = min(len(e.messages), len(target_messages))
                    for i in range(min_len):
                        await self.save_mapping(e.messages[i].id, target_messages[i].id)
                        logger.debug(f"📝 Album 매핑: {e.messages[i].id} → {target_messages[i].id}")

                logger.info(f"✅ Album 전송 완료: {len(e.messages)}개")

            except FloodWaitError as fw:
                logger.warning(f"⏰ FloodWait {fw.seconds}초 대기")
                await asyncio.sleep(fw.seconds)
                try:
                    source_ids = [m.id for m in e.messages]
                    result = await self.client.forward_messages(
                        target, source_ids, source, drop_author=True
                    )
                    # FloodWait 재시도 후에도 매핑 저장
                    if result:
                        target_messages = result if isinstance(result, list) else [result]

                        # 크기 불일치 경고
                        if len(e.messages) != len(target_messages):
                            logger.warning(f"⚠️ 재시도 후 Album 크기 불일치: {len(target_messages)}/{len(e.messages)}")

                        # 안전하게 최소 길이만큼만 매핑
                        min_len = min(len(e.messages), len(target_messages))
                        for i in range(min_len):
                            await self.save_mapping(e.messages[i].id, target_messages[i].id)
                except Exception as retry_ex:
                    logger.error(f"❌ Album FloodWait 재시도 실패: {retry_ex}")

            except ChatWriteForbiddenError:
                logger.error(f"❌ Album 전송 실패 (grouped_id={e.grouped_id}): 타겟 쓰기 권한 없음")
                await self.log("Album 전송 실패: 권한 없음", "ERROR")
            except ChannelPrivateError:
                logger.error(f"❌ Album 전송 실패 (grouped_id={e.grouped_id}): 소스 채널 접근 불가")
                await self.log("Album 전송 실패: 채널 접근 불가", "ERROR")
            except MessageIdInvalidError:
                logger.warning(f"⚠️ Album 건너뜀 (grouped_id={e.grouped_id}): 메시지 삭제됨")
            except Exception as ex:
                logger.error(f"❌ Album 전송 실패 (grouped_id={e.grouped_id}, {len(e.messages)}개): {ex}")
                await self.log(f"Album 전송 실패: {ex}", "ERROR")

    def _register_deleted_handler(self):
        """Register MessageDeleted handler for deletion sync."""

        @self.client.on(events.MessageDeleted())
        async def on_deleted_permanent(e):
            """영구 MessageDeleted 핸들러 (중복 등록 방지)"""
            if not self.get_mirroring_active():
                return

            source = self.get_source()
            target = self.get_target()

            if not source or not target or e.chat_id != source.id:
                return

            # 소스 ID → 타겟 ID 변환 (DB에서 조회)
            source_to_target = {}  # 매핑을 임시 저장
            for source_id in e.deleted_ids:
                target_id = await self.get_mapping(source_id)
                if target_id:
                    source_to_target[source_id] = target_id
                    logger.debug(f"🗑️ 삭제 매핑: {source_id} → {target_id}")

            # 타겟 메시지 삭제
            if source_to_target:
                target_ids = list(source_to_target.values())
                try:
                    await self.client.delete_messages(target, target_ids)
                    logger.info(f"🗑️ 메시지 삭제 완료: {len(target_ids)}개")

                    # 삭제 성공 후 매핑 제거
                    for source_id in source_to_target.keys():
                        await self.delete_mapping(source_id)

                except FloodWaitError as fw:
                    logger.warning(f"⏰ FloodWait {fw.seconds}초 대기")
                    await asyncio.sleep(fw.seconds)
                    try:
                        await self.client.delete_messages(target, target_ids)
                        logger.info(f"🗑️ 메시지 삭제 완료 (재시도): {len(target_ids)}개")

                        # 재시도 성공 후 매핑 제거
                        for source_id in source_to_target.keys():
                            await self.delete_mapping(source_id)
                    except Exception as retry_ex:
                        logger.error(f"❌ 삭제 재시도 실패: {retry_ex}")
                        await self.log(f"삭제 재시도 실패: {retry_ex}", "ERROR")
                        # 재시도 실패 시 매핑 유지

                except Exception as ex:
                    logger.error(f"❌ 삭제 동기화 실패: {ex}", exc_info=True)
                    await self.log(f"삭제 동기화 실패: {ex}", "ERROR")
                    # 삭제 실패 시 매핑은 유지 (재시도 가능하도록)
            else:
                logger.debug(f"⚠️ 삭제할 메시지 매핑 없음: {e.deleted_ids}")

    def _register_edited_handler(self):
        """Register MessageEdited handler for edit sync."""

        @self.client.on(events.MessageEdited())
        async def on_edited_permanent(e):
            """영구 MessageEdited 핸들러 (중복 등록 방지)"""
            if not self.get_mirroring_active():
                return

            source = self.get_source()
            target = self.get_target()

            if not source or not target or e.chat_id != source.id:
                return

            # 소스 ID → 타겟 ID 변환 (DB에서 조회)
            source_id = e.message.id
            target_id = await self.get_mapping(source_id)

            if not target_id:
                logger.debug(f"⚠️ 편집할 메시지 매핑 없음: {source_id}")
                return

            # 텍스트 메시지 편집
            if e.message.text:
                try:
                    await self.client.edit_message(
                        target,
                        target_id,
                        e.message.text
                    )
                    logger.info(f"✏️ 메시지 편집 완료: {source_id} → {target_id}")

                except FloodWaitError as fw:
                    logger.warning(f"⏰ FloodWait {fw.seconds}초 대기")
                    await asyncio.sleep(fw.seconds)
                    await self.client.edit_message(
                        target,
                        target_id,
                        e.message.text
                    )
                    logger.info(f"✏️ 메시지 편집 완료 (재시도): {source_id} → {target_id}")

                except MessageIdInvalidError:
                    logger.warning(f"⚠️ 편집할 메시지 없음: {target_id}")

                except Exception as ex:
                    logger.error(f"❌ 편집 동기화 실패: {ex}", exc_info=True)
                    await self.log(f"편집 동기화 실패 (#{source_id}): {ex}", "ERROR")
            else:
                # 미디어 메시지 편집은 Telegram API 제한으로 지원 안됨
                logger.debug(f"⚠️ 미디어 메시지 편집 불가: {source_id}")
