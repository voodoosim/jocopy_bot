"""Worker Bot - MCP 극대화 버전 (Context7 기반)"""
import asyncio
import logging
import aiosqlite
from io import BytesIO
from typing import Dict
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat, InputChatUploadedPhoto
from telethon.tl.functions.channels import (
    CreateForumTopicRequest,
    GetForumTopicsRequest,
    GetFullChannelRequest,
    CreateChannelRequest,
    EditPhotoRequest
)
from telethon.errors import (
    FloodWaitError,
    MessageIdInvalidError,
    ChatWriteForbiddenError,
    ChannelPrivateError
)

from config import API_ID, API_HASH, BATCH_SIZE, DATABASE_PATH
from .mapping_manager import MessageMappingManager
from .forum_support import ForumTopicManager
from .message_operations import MessageCopyOperations
from .event_handlers import PermanentEventHandlers

logger = logging.getLogger(__name__)


class WorkerBot:
    """MCP 극대화 워커 봇 (forward_messages + Album 지원)"""

    def __init__(self, worker_id: int, worker_name: str, session_string: str):
        self.worker_id = worker_id
        self.worker_name = worker_name

        self.client = TelegramClient(
            StringSession(session_string),
            API_ID,
            API_HASH
        )

        # 소스/타겟
        self.source = None
        self.target = None

        # 미러링 활성화 플래그 (중복 등록 방지용)
        self.mirroring_active = False

        self._setup_handlers()

        # Initialize managers
        self.mapping_manager = MessageMappingManager(self.worker_id, self.worker_name)
        self.forum_manager = ForumTopicManager(self.client, self.worker_id, self.worker_name)
        self.copy_ops = MessageCopyOperations(
            client=self.client,
            mapping_manager=self.mapping_manager,
            forum_manager=self.forum_manager,
            log_callback=self.log
        )

        # Register permanent event handlers
        self.event_handlers = PermanentEventHandlers(
            client=self.client,
            log_callback=self.log,
            get_mirroring_active=lambda: self.mirroring_active,
            get_source=lambda: self.source,
            get_target=lambda: self.target,
            get_topic_mapping=lambda: self.forum_manager.topic_mapping,
            save_mapping=lambda src_id, tgt_id: self.mapping_manager.save_mapping(
                self.source, self.target, src_id, tgt_id
            ),
            get_mapping=lambda src_id: self.mapping_manager.get_mapping(self.source, src_id),
            delete_mapping=lambda src_id: self.mapping_manager.delete_mapping(self.source, src_id),
        )
        self.event_handlers.register_handlers()

    def _setup_handlers(self):
        """명령어 등록"""

        @self.client.on(events.NewMessage(pattern=r'^\.목록$', from_users="me"))
        async def list_chats(event):
            """채널 및 그룹 목록 (구분하여 표시)"""
            channels = []
            groups = []

            async for d in self.client.iter_dialogs():
                if isinstance(d.entity, Channel):
                    if d.entity.broadcast:
                        # 방송 채널
                        channels.append(d.title)
                    else:
                        # 슈퍼그룹
                        groups.append(d.title)
                elif isinstance(d.entity, Chat):
                    # 일반 그룹
                    groups.append(d.title)

            # 채널/그룹별로 정리해서 표시
            text = ""
            if channels:
                text += "📢 **채널:**\n"
                for i, title in enumerate(channels, 1):
                    text += f"{i}. {title}\n"
            else:
                text += "📢 **채널:** 없음\n"

            text += "\n"

            if groups:
                text += "👥 **그룹:**\n"
                for i, title in enumerate(groups, 1):
                    text += f"{i}. {title}\n"
            else:
                text += "👥 **그룹:** 없음"

            await event.reply(text if text.strip() else "❌ 채널/그룹 없음")

        @self.client.on(events.NewMessage(pattern=r'^\.설정$', from_users="me"))
        async def setup(event):
            """소스/타겟 설정 (채널/그룹 구분)"""
            # 채널과 그룹 분리
            channels = []
            groups = []

            async for d in self.client.iter_dialogs():
                if isinstance(d.entity, Channel):
                    if d.entity.broadcast:
                        channels.append((d.entity, d.title))
                    else:
                        groups.append((d.entity, d.title))
                elif isinstance(d.entity, Chat):
                    groups.append((d.entity, d.title))

            all_chats = channels + groups

            if not all_chats:
                return await event.reply("❌ 채널/그룹 없음")

            # conversation API 사용 (Saved Messages - me.id 사용)
            me = await self.client.get_me()
            async with self.client.conversation(me.id) as conv:
                # 목록 표시 (채널/그룹 명확히 구분)
                text = "📋 **채팅 목록**\n\n"

                # 그룹 섹션
                text += "⁘ **그룹** ⁘\n\n"
                if groups:
                    for i, (entity, title) in enumerate(groups, 1):
                        text += f"g{i}. 👥 {title}\n"
                else:
                    text += "   (없음)\n"

                text += "\n"

                # 채널 섹션
                text += "⁘ **채널** ⁘\n\n"
                if channels:
                    for i, (entity, title) in enumerate(channels, 1):
                        text += f"c{i}. 📢 {title}\n"
                else:
                    text += "   (없음)\n"

                await conv.send_message(
                    f"{text}\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"📤 **소스 입력** (예: c1 또는 g2):"
                )

                # 소스 선택
                try:
                    resp = await conv.get_response(timeout=60)
                    source_input = resp.text.strip().lower()
                except asyncio.TimeoutError:
                    await conv.send_message("⏰ 시간 초과 (60초). 다시 시도하세요.")
                    self.source = None
                    return

                # 입력 파싱 (c1, g2 등)
                if source_input.startswith('c'):
                    try:
                        num = int(source_input[1:])
                        if num < 1 or num > len(channels):
                            await conv.send_message(
                                f"❌ 잘못된 채널 번호! c1~c{len(channels)} 입력"
                            )
                            return
                        self.source = channels[num - 1][0]
                        source_name = channels[num - 1][1]
                    except (ValueError, IndexError):
                        await conv.send_message("❌ 형식 오류! 예: c1, c2")
                        return
                elif source_input.startswith('g'):
                    try:
                        num = int(source_input[1:])
                        if num < 1 or num > len(groups):
                            await conv.send_message(
                                f"❌ 잘못된 그룹 번호! g1~g{len(groups)} 입력"
                            )
                            return
                        self.source = groups[num - 1][0]
                        source_name = groups[num - 1][1]
                    except (ValueError, IndexError):
                        await conv.send_message("❌ 형식 오류! 예: g1, g2")
                        return
                else:
                    await conv.send_message("❌ c(채널) 또는 g(그룹)로 시작! 예: c1, g2")
                    return

                await conv.send_message(
                    f"✅ 소스: {source_name}\n\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"📥 **타겟 입력** (예: c1 또는 g2):"
                )

                # 타겟 선택
                try:
                    resp = await conv.get_response(timeout=60)
                    target_input = resp.text.strip().lower()
                except asyncio.TimeoutError:
                    await conv.send_message("⏰ 시간 초과 (60초). 다시 시도하세요.")
                    self.source = None
                    self.target = None
                    return

                # 입력 파싱 (c1, g2 등)
                if target_input.startswith('c'):
                    try:
                        num = int(target_input[1:])
                        if num < 1 or num > len(channels):
                            await conv.send_message(
                                f"❌ 잘못된 채널 번호! c1~c{len(channels)} 입력"
                            )
                            self.source = None
                            return
                        self.target = channels[num - 1][0]
                        target_name = channels[num - 1][1]
                    except (ValueError, IndexError):
                        await conv.send_message("❌ 형식 오류! 예: c1, c2")
                        self.source = None
                        return
                elif target_input.startswith('g'):
                    try:
                        num = int(target_input[1:])
                        if num < 1 or num > len(groups):
                            await conv.send_message(
                                f"❌ 잘못된 그룹 번호! g1~g{len(groups)} 입력"
                            )
                            self.source = None
                            return
                        self.target = groups[num - 1][0]
                        target_name = groups[num - 1][1]
                    except (ValueError, IndexError):
                        await conv.send_message("❌ 형식 오류! 예: g1, g2")
                        self.source = None
                        return
                else:
                    await conv.send_message("❌ c(채널) 또는 g(그룹)로 시작! 예: c1, g2")
                    self.source = None
                    return

                # 타겟 권한 체크
                try:
                    # 테스트 메시지 전송 후 즉시 삭제
                    test_msg = await self.client.send_message(
                        self.target,
                        "🔧 권한 체크 중..."
                    )
                    await test_msg.delete()

                    await conv.send_message(
                        f"✅ **설정 완료!**\n\n"
                        f"📤 **소스:** {source_name}\n"
                        f"📥 **타겟:** {target_name}\n"
                        f"✅ 타겟 쓰기 권한 확인됨\n\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"**다음 명령어:**\n"
                        f"• `.미러` - 실시간 미러링 시작\n"
                        f"• `.카피` - 전체 메시지 복사\n"
                        f"• `.설정` - 다시 설정"
                    )
                except ChatWriteForbiddenError:
                    await conv.send_message(
                        f"❌ 타겟 채널 쓰기 권한 없음!\n\n"
                        f"📥 타겟: {target_name}\n\n"
                        f"**해결 방법:**\n"
                        f"1. 타겟 채널에서 이 계정을 관리자로 추가\n"
                        f"2. '메시지 게시' 권한 활성화\n"
                        f"3. 다시 .설정 실행"
                    )
                    self.target = None
                except Exception as e:
                    await conv.send_message(f"❌ 권한 체크 실패: {str(e)}")
                    self.target = None

        @self.client.on(events.NewMessage(pattern=r'^\.소스입력$', from_users="me"))
        async def set_source(event):
            """소스 채널/그룹 설정 (독립 명령)"""
            # 채팅 목록 가져오기
            all_chats = []
            channels = []
            groups = []

            async for dialog in self.client.iter_dialogs():
                entity = dialog.entity
                title = dialog.title or "이름 없음"

                # 채널 구분
                if isinstance(entity, Channel) and entity.broadcast:
                    channels.append((entity, title))
                # 그룹 구분
                elif isinstance(entity, Chat) or (
                    isinstance(entity, Channel) and not entity.broadcast
                ):
                    groups.append((entity, title))

            # conversation API 사용
            me = await self.client.get_me()
            async with self.client.conversation(me.id) as conv:
                # 목록 표시
                text = "📋 **소스 채널/그룹 선택**\n\n"

                # 그룹 섹션
                text += "⁘ **그룹** ⁘\n\n"
                if groups:
                    for i, (entity, title) in enumerate(groups, 1):
                        text += f"g{i}. 👥 {title}\n"
                else:
                    text += "   (없음)\n"

                text += "\n"

                # 채널 섹션
                text += "⁘ **채널** ⁘\n\n"
                if channels:
                    for i, (entity, title) in enumerate(channels, 1):
                        text += f"c{i}. 📢 {title}\n"
                else:
                    text += "   (없음)\n"

                text += "\n━━━━━━━━━━━━━━━━\n"
                text += "**입력 예시:** c1 (채널 1번), g2 (그룹 2번)"

                await conv.send_message(text)

                # 사용자 입력 대기
                try:
                    resp = await conv.get_response(timeout=60)
                    source_input = resp.text.strip().lower()
                except asyncio.TimeoutError:
                    await conv.send_message("⏰ 시간 초과 (60초). 다시 시도하세요.")
                    self.source = None
                    return

                # 입력 파싱 (c1, g2 등)
                source_name = None
                if source_input.startswith('c'):
                    try:
                        num = int(source_input[1:])
                        if num < 1 or num > len(channels):
                            await conv.send_message(
                                f"❌ 잘못된 채널 번호! c1~c{len(channels)} 입력"
                            )
                            return
                        self.source = channels[num - 1][0]
                        source_name = channels[num - 1][1]
                    except (ValueError, IndexError):
                        await conv.send_message("❌ 형식 오류! 예: c1, c2")
                        return
                elif source_input.startswith('g'):
                    try:
                        num = int(source_input[1:])
                        if num < 1 or num > len(groups):
                            await conv.send_message(
                                f"❌ 잘못된 그룹 번호! g1~g{len(groups)} 입력"
                            )
                            return
                        self.source = groups[num - 1][0]
                        source_name = groups[num - 1][1]
                    except (ValueError, IndexError):
                        await conv.send_message("❌ 형식 오류! 예: g1, g2")
                        return
                else:
                    await conv.send_message("❌ c(채널) 또는 g(그룹)로 시작! 예: c1, g2")
                    return

                # 성공 메시지
                await conv.send_message(
                    f"✅ **소스 설정 완료!**\n\n"
                    f"📤 **소스:** {source_name}\n\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"**다음 단계:**\n"
                    f"• `.타겟입력` - 타겟 채널/그룹 설정\n"
                    f"• `.설정` - 소스와 타겟 한번에 설정"
                )

        @self.client.on(events.NewMessage(pattern=r'^\.타겟입력$', from_users="me"))
        async def set_target(event):
            """타겟 채널/그룹 설정 (독립 명령)"""
            # 채팅 목록 가져오기
            all_chats = []
            channels = []
            groups = []

            async for dialog in self.client.iter_dialogs():
                entity = dialog.entity
                title = dialog.title or "이름 없음"

                # 채널 구분
                if isinstance(entity, Channel) and entity.broadcast:
                    channels.append((entity, title))
                # 그룹 구분
                elif isinstance(entity, Chat) or (
                    isinstance(entity, Channel) and not entity.broadcast
                ):
                    groups.append((entity, title))

            # conversation API 사용
            me = await self.client.get_me()
            async with self.client.conversation(me.id) as conv:
                # 목록 표시
                text = "📋 **타겟 채널/그룹 선택**\n\n"

                # 그룹 섹션
                text += "⁘ **그룹** ⁘\n\n"
                if groups:
                    for i, (entity, title) in enumerate(groups, 1):
                        text += f"g{i}. 👥 {title}\n"
                else:
                    text += "   (없음)\n"

                text += "\n"

                # 채널 섹션
                text += "⁘ **채널** ⁘\n\n"
                if channels:
                    for i, (entity, title) in enumerate(channels, 1):
                        text += f"c{i}. 📢 {title}\n"
                else:
                    text += "   (없음)\n"

                text += "\n━━━━━━━━━━━━━━━━\n"
                text += "**입력 예시:** c1 (채널 1번), g2 (그룹 2번)"

                await conv.send_message(text)

                # 사용자 입력 대기
                try:
                    resp = await conv.get_response(timeout=60)
                    target_input = resp.text.strip().lower()
                except asyncio.TimeoutError:
                    await conv.send_message("⏰ 시간 초과 (60초). 다시 시도하세요.")
                    self.target = None
                    return

                # 입력 파싱 (c1, g2 등)
                target_name = None
                if target_input.startswith('c'):
                    try:
                        num = int(target_input[1:])
                        if num < 1 or num > len(channels):
                            await conv.send_message(
                                f"❌ 잘못된 채널 번호! c1~c{len(channels)} 입력"
                            )
                            return
                        self.target = channels[num - 1][0]
                        target_name = channels[num - 1][1]
                    except (ValueError, IndexError):
                        await conv.send_message("❌ 형식 오류! 예: c1, c2")
                        return
                elif target_input.startswith('g'):
                    try:
                        num = int(target_input[1:])
                        if num < 1 or num > len(groups):
                            await conv.send_message(
                                f"❌ 잘못된 그룹 번호! g1~g{len(groups)} 입력"
                            )
                            return
                        self.target = groups[num - 1][0]
                        target_name = groups[num - 1][1]
                    except (ValueError, IndexError):
                        await conv.send_message("❌ 형식 오류! 예: g1, g2")
                        return
                else:
                    await conv.send_message("❌ c(채널) 또는 g(그룹)로 시작! 예: c1, g2")
                    return

                # 타겟 쓰기 권한 확인
                try:
                    test_msg = await self.client.send_message(
                        self.target, "✅ 권한 체크 (자동 삭제)"
                    )
                    await asyncio.sleep(1)
                    await test_msg.delete()

                    # 성공 메시지
                    await conv.send_message(
                        f"✅ **타겟 설정 완료!**\n\n"
                        f"📥 **타겟:** {target_name}\n"
                        f"✅ 타겟 쓰기 권한 확인됨\n\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"**다음 명령어:**\n"
                        f"• `.미러` - 실시간 미러링 시작\n"
                        f"• `.카피` - 전체 메시지 복사"
                    )
                except ChatWriteForbiddenError:
                    await conv.send_message(
                        f"❌ **타겟 쓰기 권한 없음!**\n\n"
                        f"**타겟:** {target_name}\n\n"
                        f"**해결 방법:**\n"
                        f"1. 타겟 채널에서 이 계정을 관리자로 추가\n"
                        f"2. '메시지 게시' 권한 활성화\n"
                        f"3. 다시 `.타겟입력` 실행"
                    )
                    self.target = None
                except Exception as e:
                    await conv.send_message(f"❌ 권한 체크 실패: {str(e)}")
                    self.target = None

        @self.client.on(events.NewMessage(pattern=r'^\.미러$', from_users="me"))
        async def mirror(event):
            """
            미러링 시작 (MCP 최적화)
            - 영구 핸들러 사용 (중복 등록 없음!)
            - DB 매핑 로드 + 초기 복사 + 플래그 활성화
            """
            if not self.source or not self.target:
                return await event.reply("❌ .설정 먼저 하세요")

            # Bug #2 수정: 중복 실행 경고 + Race Condition 방지
            if self.mirroring_active:
                return await event.reply(
                    "⚠️ 미러링이 이미 실행 중입니다\n\n"
                    "중복 복사를 원하면 먼저 `.중지` 후 다시 실행하세요"
                )

            # Race Condition 방지: 플래그를 먼저 설정
            self.mirroring_active = True

            try:
                await event.reply("🔄 미러링 시작...")
                await self.log("미러링 시작", "START")

                # 0. DB에서 기존 매핑 로드 (Bug #3 수정: 재시작 후에도 편집/삭제 동기화)
                await self.mapping_manager.load_mappings_from_db(self.source)

                # Forum 확인 및 토픽 동기화
                is_forum = await self.forum_manager.is_forum(self.source)
                if is_forum:
                    await event.reply("📂 Forum 감지! 토픽 동기화 중...")
                    await self.forum_manager.sync_forum_topics(self.source, self.target)
                    # Bug #4 경고: Forum 토픽은 실시간 미러링에서 무시됨
                    await event.reply(
                        "⚠️ 주의: Forum 토픽 구조는 초기 복사에만 적용됩니다\n"
                        "실시간 미러링은 모든 메시지가 General 토픽으로 전송됩니다"
                    )

                # 1. 전체 복사 (초기 동기화)
                count = await self.copy_ops.copy_all(self.source, self.target)

                # 2. 실시간 미러링은 이미 활성화됨 (상단에서 플래그 설정)

                if is_forum:
                    await event.reply(
                        f"✅ 초기 복사: {count}개\n"
                        f"📂 Forum 토픽: {len(self.forum_manager.topic_mapping)}개\n"
                        f"📝 기존 매핑: {self.mapping_manager.get_cache_size()}개\n"
                        f"🔄 실시간 동기화 활성\n\n"
                        f"💡 `.중지` 명령으로 미러링 중지 가능"
                    )
                else:
                    await event.reply(
                        f"✅ 초기 복사: {count}개\n"
                        f"📝 기존 매핑: {self.mapping_manager.get_cache_size()}개\n"
                        f"🔄 실시간 동기화 활성\n\n"
                        f"💡 `.중지` 명령으로 미러링 중지 가능"
                    )

                await self.log(f"초기 복사 완료: {count}개, 실시간 동기화 활성화", "SUCCESS")

            except Exception as e:
                # 에러 발생 시 플래그 해제
                self.mirroring_active = False
                await event.reply(f"❌ 미러링 시작 실패: {str(e)}")
                await self.log(f"미러링 시작 실패: {e}", "ERROR")
                raise

        @self.client.on(events.NewMessage(pattern=r'^\.중지$', from_users="me"))
        async def stop_mirror(event):
            """미러링 중지"""
            if self.mirroring_active:
                self.mirroring_active = False
                await event.reply("🛑 미러링 중지됨")
                await self.log("미러링 중지", "STOP")
            else:
                await event.reply("ℹ️ 미러링이 실행 중이지 않습니다")

        @self.client.on(events.NewMessage(pattern=r'^\.카피$', from_users="me"))
        async def copy(event):
            """전체 복사 (forward_messages)"""
            if not self.source or not self.target:
                return await event.reply("❌ .설정 먼저 하세요")

            msg = await event.reply("📤 복사 시작...")
            await self.log("전체 복사 시작", "START")

            count = await self.copy_ops.copy_all(self.source, self.target, progress_msg=msg)

            await msg.edit(f"✅ 복사 완료: {count}개")
            await self.log(f"전체 복사 완료: {count}개", "SUCCESS")

        @self.client.on(events.NewMessage(pattern=r'^\.그룹복사$', from_users="me"))
        async def clone_group(event):
            """
            그룹 정보를 복사하여 새 그룹 생성
            - 제목, 설명, 프로필 사진 복사
            - 생성된 그룹을 자동으로 target으로 설정
            - 메시지는 .미러로 별도 복사 필요
            """
            if not self.source:
                return await event.reply("❌ .소스입력 먼저 하세요")

            try:
                await event.reply("🔄 그룹 정보 복사 시작...")

                # 1. 소스 그룹 정보 가져오기
                source_entity = await self.client.get_entity(self.source)

                # 채널인 경우
                if isinstance(source_entity, Channel):
                    if source_entity.broadcast:
                        return await event.reply("❌ 채널은 그룹 복사 불가능합니다\n.설정을 사용하세요")

                    # 슈퍼그룹/메가그룹
                    source_title = source_entity.title
                    full_chat = await self.client(GetFullChannelRequest(channel=source_entity))
                    source_about = full_chat.full_chat.about or ""

                # 일반 그룹
                elif isinstance(source_entity, Chat):
                    source_title = source_entity.title
                    source_about = ""

                else:
                    return await event.reply("❌ 소스가 그룹이 아닙니다")

                # 설명 텍스트 포맷팅
                description_text = source_about[:100] + "..." if source_about and len(source_about) > 100 else source_about if source_about else "(없음)"

                await event.reply(
                    f"📋 복사할 그룹 정보:\n\n"
                    f"**제목:** {source_title}\n"
                    f"**설명:** {description_text}"
                )

                # 2. 새 그룹 생성
                # 제목 길이 제한 (UTF-8 안전하게 절단)
                if len(source_title.encode('utf-8')) > 255:
                    # UTF-8 바이트 레벨로 절단
                    truncated = source_title.encode('utf-8')[:252]
                    source_title = truncated.decode('utf-8', errors='ignore') + "..."

                # 슈퍼그룹 생성 (메가그룹)
                result = await self.client(CreateChannelRequest(
                    title=source_title,
                    about=source_about[:255] if source_about else "",  # about도 길이 제한
                    megagroup=True  # 슈퍼그룹으로 생성
                ))

                # 생성된 채널 정보
                if not result.chats:
                    raise ValueError("그룹 생성 실패: 결과에 채팅이 없습니다")

                new_group = result.chats[0]
                new_group_id = new_group.id

                await event.reply(f"✅ 그룹 생성 완료: **{source_title}**")

                # 3. 프로필 사진 복사 (선택적) + BytesIO 리소스 관리
                photo_bytes = BytesIO()
                try:
                    # 소스 프로필 사진 다운로드
                    photo = await self.client.download_profile_photo(self.source, file=photo_bytes)
                    if photo:
                        # 새 그룹에 업로드
                        photo_bytes.seek(0)
                        uploaded_file = await self.client.upload_file(photo_bytes)
                        input_photo = InputChatUploadedPhoto(uploaded_file)
                        await self.client(EditPhotoRequest(
                            channel=new_group,
                            photo=input_photo
                        ))
                        await event.reply("✅ 프로필 사진 복사 완료")
                except Exception as e:
                    logger.warning(f"프로필 사진 복사 실패: {e}")
                    await event.reply("⚠️ 프로필 사진 복사 실패 (선택적 기능)")
                finally:
                    # 항상 BytesIO 리소스 해제
                    photo_bytes.close()

                # 4. 자동으로 target 설정
                self.target = new_group

                await event.reply(
                    f"🎉 **그룹 복사 완료!**\n\n"
                    f"📂 새 그룹: {source_title}\n"
                    f"🆔 그룹 ID: `{new_group_id}`\n\n"
                    f"✅ Target이 자동으로 설정되었습니다\n"
                    f"💡 이제 `.미러` 명령으로 메시지를 복사하세요"
                )

                await self.log(f"그룹 복사 완료: {source_title} (ID: {new_group_id})", "SUCCESS")

            except Exception as e:
                logger.error(f"그룹 복사 실패: {e}", exc_info=True)
                await event.reply(f"❌ 그룹 복사 실패: {str(e)}")
                await self.log(f"그룹 복사 실패: {e}", "ERROR")

        @self.client.on(events.NewMessage(pattern=r'^\.지정\s+(\d+)$', from_users="me"))
        async def copy_from(event):
            """범위 복사 (forward_messages)"""
            if not self.source or not self.target:
                return await event.reply("❌ .설정 먼저 하세요")

            start_id = int(event.pattern_match.group(1))
            msg = await event.reply(f"📤 #{start_id}부터 복사 중...")
            await self.log(f"범위 복사 시작 (#{start_id}~)", "START")

            count = await self.copy_ops.copy_all(self.source, self.target, min_id=start_id-1, progress_msg=msg)

            await msg.edit(f"✅ 복사 완료: {count}개")
            await self.log(f"범위 복사 완료: {count}개", "SUCCESS")

    async def log(self, message: str, level: str = "INFO"):
        """로그를 DB에 저장 (Main Bot이 나중에 전송)"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    """
                    INSERT INTO logs (worker_id, worker_name, level, message)
                    VALUES (?, ?, ?, ?)
                    """,
                    (self.worker_id, self.worker_name, level, message)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"로그 저장 실패: {e}")

    async def start(self):
        """워커 시작 (예외 처리 및 Cleanup 추가)"""
        try:
            await self.client.start()
            me = await self.client.get_me()
            logger.info(f"✅ Worker '{self.worker_name}' 로그인: @{me.username}")

            # DB 상태 업데이트: starting → running
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    "UPDATE workers SET status = 'running' WHERE id = ?",
                    (self.worker_id,)
                )
                await db.commit()

            await self.client.run_until_disconnected()

        except Exception as e:
            logger.error(f"❌ Worker 실행 실패: {e}", exc_info=True)
            await self.log(f"Worker 실행 실패: {e}", "ERROR")
        finally:
            # Cleanup: 항상 DB 상태 업데이트 및 연결 종료
            try:
                async with aiosqlite.connect(DATABASE_PATH) as db:
                    await db.execute(
                        "UPDATE workers SET status = 'stopped', process_id = NULL WHERE id = ?",
                        (self.worker_id,)
                    )
                    await db.commit()
                logger.info(f"✅ Worker '{self.worker_name}' 정리 완료")
            except Exception as cleanup_ex:
                logger.error(f"❌ Cleanup 실패: {cleanup_ex}")

            try:
                await self.client.disconnect()
            except:
                pass
