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

        # 메시지 ID 매핑 (소스 메시지 ID → 타겟 메시지 ID)
        # 편집/삭제 동기화에 필요
        self.message_map: Dict[int, int] = {}

        # Forum 토픽 매핑 (소스 토픽 ID → 타겟 토픽 ID)
        self.topic_mapping = {}

        self._setup_handlers()

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
                await self._load_mappings_from_db()

                # Forum 확인 및 토픽 동기화
                is_forum = await self._is_forum(self.source)
                if is_forum:
                    await event.reply("📂 Forum 감지! 토픽 동기화 중...")
                    await self._sync_forum_topics()
                    # Bug #4 경고: Forum 토픽은 실시간 미러링에서 무시됨
                    await event.reply(
                        "⚠️ 주의: Forum 토픽 구조는 초기 복사에만 적용됩니다\n"
                        "실시간 미러링은 모든 메시지가 General 토픽으로 전송됩니다"
                    )

                # 1. 전체 복사 (초기 동기화)
                count = await self._copy_all()

                # 2. 실시간 미러링은 이미 활성화됨 (상단에서 플래그 설정)

                if is_forum:
                    await event.reply(
                        f"✅ 초기 복사: {count}개\n"
                        f"📂 Forum 토픽: {len(self.topic_mapping)}개\n"
                        f"📝 기존 매핑: {len(self.message_map)}개\n"
                        f"🔄 실시간 동기화 활성\n\n"
                        f"💡 `.중지` 명령으로 미러링 중지 가능"
                    )
                else:
                    await event.reply(
                        f"✅ 초기 복사: {count}개\n"
                        f"📝 기존 매핑: {len(self.message_map)}개\n"
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

            count = await self._copy_all(progress_msg=msg)

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

            count = await self._copy_all(min_id=start_id-1, progress_msg=msg)

            await msg.edit(f"✅ 복사 완료: {count}개")
            await self.log(f"범위 복사 완료: {count}개", "SUCCESS")

        # ========================================
        # 영구 이벤트 핸들러 (한 번만 등록)
        # mirroring_active 플래그로 활성화 제어
        # ========================================

        @self.client.on(events.NewMessage())
        async def on_new_permanent(e):
            """영구 NewMessage 핸들러 (중복 등록 방지)"""
            # 미러링 비활성 또는 소스 불일치 시 무시
            if not self.mirroring_active:
                return
            if not self.source or not self.target or e.chat_id != self.source.id:
                return
            # Album 메시지는 on_album에서 처리
            if e.message.grouped_id:
                return

            try:
                # 토픽 ID 확인 (Forum)
                topic_id = getattr(e.message, 'message_thread_id', None)
                target_topic_id = self.topic_mapping.get(topic_id) if topic_id else None

                if target_topic_id:
                    logger.info(f"토픽 메시지 복사: #{e.message.id} → 토픽 #{target_topic_id}")

                # MCP 방식으로 전송
                result = await self.client.forward_messages(
                    self.target,
                    e.message.id,
                    self.source,
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
                        await self._save_mapping(e.message.id, target_id)
                        logger.debug(f"📝 매핑 저장: {e.message.id} → {target_id}")

            except FloodWaitError as fw:
                logger.warning(f"⏰ FloodWait {fw.seconds}초 대기")
                await asyncio.sleep(fw.seconds)
                try:
                    result = await self.client.forward_messages(
                        self.target, e.message.id, self.source, drop_author=True
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
                            await self._save_mapping(e.message.id, target_id)
                except Exception as retry_ex:
                    logger.error(f"❌ FloodWait 재시도 실패: {retry_ex}")
            except MessageIdInvalidError:
                logger.warning(f"⚠️ 메시지 #{e.message.id} 건너뜀")
            except ChatWriteForbiddenError:
                logger.error("❌ 타겟 채널 쓰기 권한 없음!")
            except ChannelPrivateError:
                logger.error("❌ 소스 채널 접근 권한 없음!")

        @self.client.on(events.Album())
        async def on_album_permanent(e):
            """영구 Album 핸들러 (중복 등록 방지)"""
            if not self.mirroring_active:
                return
            if not self.source or not self.target or e.chat_id != self.source.id:
                return

            try:
                # MCP 방식으로 Album 전송
                source_ids = [m.id for m in e.messages]
                result = await self.client.forward_messages(
                    self.target,
                    source_ids,
                    self.source,
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
                        await self._save_mapping(e.messages[i].id, target_messages[i].id)
                        logger.debug(f"📝 Album 매핑: {e.messages[i].id} → {target_messages[i].id}")

                logger.info(f"✅ Album 전송 완료: {len(e.messages)}개")

            except FloodWaitError as fw:
                logger.warning(f"⏰ FloodWait {fw.seconds}초 대기")
                await asyncio.sleep(fw.seconds)
                try:
                    source_ids = [m.id for m in e.messages]
                    result = await self.client.forward_messages(
                        self.target, source_ids, self.source, drop_author=True
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
                            await self._save_mapping(e.messages[i].id, target_messages[i].id)
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

        @self.client.on(events.MessageDeleted())
        async def on_deleted_permanent(e):
            """영구 MessageDeleted 핸들러 (중복 등록 방지)"""
            if not self.mirroring_active:
                return
            if not self.source or not self.target or e.chat_id != self.source.id:
                return

            # 소스 ID → 타겟 ID 변환 (DB에서 조회)
            source_to_target = {}  # 매핑을 임시 저장
            for source_id in e.deleted_ids:
                target_id = await self._get_mapping(source_id)
                if target_id:
                    source_to_target[source_id] = target_id
                    logger.debug(f"🗑️ 삭제 매핑: {source_id} → {target_id}")

            # 타겟 메시지 삭제
            if source_to_target:
                target_ids = list(source_to_target.values())
                try:
                    await self.client.delete_messages(self.target, target_ids)
                    logger.info(f"🗑️ 메시지 삭제 완료: {len(target_ids)}개")

                    # 삭제 성공 후 매핑 제거
                    for source_id in source_to_target.keys():
                        await self._delete_mapping(source_id)

                except FloodWaitError as fw:
                    logger.warning(f"⏰ FloodWait {fw.seconds}초 대기")
                    await asyncio.sleep(fw.seconds)
                    try:
                        await self.client.delete_messages(self.target, target_ids)
                        logger.info(f"🗑️ 메시지 삭제 완료 (재시도): {len(target_ids)}개")

                        # 재시도 성공 후 매핑 제거
                        for source_id in source_to_target.keys():
                            await self._delete_mapping(source_id)
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

        @self.client.on(events.MessageEdited())
        async def on_edited_permanent(e):
            """영구 MessageEdited 핸들러 (중복 등록 방지)"""
            if not self.mirroring_active:
                return
            if not self.source or not self.target or e.chat_id != self.source.id:
                return

            # 소스 ID → 타겟 ID 변환 (DB에서 조회)
            source_id = e.message.id
            target_id = await self._get_mapping(source_id)

            if not target_id:
                logger.debug(f"⚠️ 편집할 메시지 매핑 없음: {source_id}")
                return

            # 텍스트 메시지 편집
            if e.message.text:
                try:
                    await self.client.edit_message(
                        self.target,
                        target_id,
                        e.message.text
                    )
                    logger.info(f"✏️ 메시지 편집 완료: {source_id} → {target_id}")
                except FloodWaitError as fw:
                    logger.warning(f"⏰ FloodWait {fw.seconds}초 대기")
                    await asyncio.sleep(fw.seconds)
                    await self.client.edit_message(
                        self.target,
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

    # ========================================
    # Message ID Mapping (DB 영구 저장)
    # Bug #3 수정: 메모리 대신 DB에 저장하여 재시작 후에도 유지
    # ========================================

    async def _save_mapping(self, source_msg_id: int, target_msg_id: int):
        """메시지 ID 매핑을 DB에 저장"""
        if not self.source or not self.target:
            return

        source_chat_id = str(self.source.id) if hasattr(self.source, 'id') else str(self.source)
        target_chat_id = str(self.target.id) if hasattr(self.target, 'id') else str(self.target)

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
            # DB 저장 실패 시 메모리에도 저장하지 않음 (일관성 유지)

    async def _get_mapping(self, source_msg_id: int) -> int:
        """메시지 ID 매핑 조회 (메모리 캐시 우선, 없으면 DB)"""
        # 1. 메모리 캐시 확인
        if source_msg_id in self.message_map:
            return self.message_map[source_msg_id]

        # 2. DB에서 조회
        if not self.source:
            return None

        source_chat_id = str(self.source.id) if hasattr(self.source, 'id') else str(self.source)

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

        return None

    async def _load_mappings_from_db(self):
        """DB에서 기존 매핑을 메모리로 로드 (워커 시작 시)"""
        if not self.source:
            return

        source_chat_id = str(self.source.id) if hasattr(self.source, 'id') else str(self.source)

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
        except Exception as e:
            logger.error(f"매핑 로드 실패: {e}")

    async def _delete_mapping(self, source_msg_id: int):
        """메시지 삭제 시 매핑도 제거"""
        if not self.source:
            return

        source_chat_id = str(self.source.id) if hasattr(self.source, 'id') else str(self.source)

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
            # DB 삭제 실패 시 메모리도 건드리지 않음 (일관성 유지)

    # ========================================
    # Forum Topics 지원 메소드
    # ========================================

    async def _is_forum(self, chat) -> bool:
        """채널이 Forum인지 확인"""
        try:
            entity = await self.client.get_entity(chat)
            return getattr(entity, 'forum', False)
        except Exception as e:
            logger.error(f"Forum 확인 실패: {e}")
            return False

    async def _get_forum_topics(self, chat) -> list:
        """Forum의 모든 토픽 가져오기"""
        try:
            result = await self.client(GetForumTopicsRequest(
                channel=chat,
                offset_date=0,
                offset_id=0,
                offset_topic=0,
                limit=100
            ))
            return result.topics if hasattr(result, 'topics') else []
        except Exception as e:
            logger.error(f"토픽 조회 실패: {e}")
            return []

    async def _create_matching_topic(self, title: str, icon_color: int = None, icon_emoji_id: int = None) -> int:
        """타겟에 동일한 토픽 생성"""
        try:
            result = await self.client(CreateForumTopicRequest(
                channel=self.target,
                title=title,
                icon_color=icon_color or 0x6FB9F0,  # 기본 파란색
                icon_emoji_id=icon_emoji_id or 0
            ))
            # 생성된 토픽 ID 반환 (reply_to_top_id 사용)
            if result.updates and result.updates[0].message:
                msg = result.updates[0].message
                if hasattr(msg, 'reply_to') and msg.reply_to:
                    return getattr(msg.reply_to, 'reply_to_top_id', None)
            return None
        except Exception as e:
            logger.error(f"토픽 생성 실패 ({title}): {e}")
            return None

    async def _sync_forum_topics(self) -> dict:
        """소스와 타겟의 토픽 동기화 및 매핑 생성"""
        mapping = {}

        # 소스 토픽 가져오기
        source_topics = await self._get_forum_topics(self.source)
        if not source_topics:
            logger.info("소스에 토픽 없음 (일반 채널)")
            return mapping

        await self.log(f"Forum 토픽 동기화 시작: {len(source_topics)}개", "INFO")

        # 각 토픽 복사
        for topic in source_topics:
            source_topic_id = topic.id
            topic_title = topic.title

            # 타겟에 동일한 토픽 생성
            target_topic_id = await self._create_matching_topic(
                title=topic_title,
                icon_color=getattr(topic, 'icon_color', None),
                icon_emoji_id=getattr(topic, 'icon_emoji_id', None)
            )

            if target_topic_id:
                mapping[source_topic_id] = target_topic_id

                # DB에 매핑 저장
                try:
                    async with aiosqlite.connect(DATABASE_PATH) as db:
                        await db.execute(
                            """
                            INSERT OR REPLACE INTO topic_mappings
                            (worker_id, source_chat_id, target_chat_id, source_topic_id, target_topic_id, topic_title)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                self.worker_id,
                                str(self.source.id if hasattr(self.source, 'id') else self.source),
                                str(self.target.id if hasattr(self.target, 'id') else self.target),
                                source_topic_id,
                                target_topic_id,
                                topic_title
                            )
                        )
                        await db.commit()
                except Exception as e:
                    logger.error(f"토픽 매핑 DB 저장 실패: {e}")

                await self.log(f"토픽 생성 완료: {topic_title} (소스 #{source_topic_id} → 타겟 #{target_topic_id})", "SUCCESS")
            else:
                await self.log(f"토픽 생성 실패: {topic_title}", "ERROR")

        self.topic_mapping = mapping
        await self.log(f"Forum 토픽 동기화 완료: {len(mapping)}개", "SUCCESS")
        return mapping

    async def _copy_all(self, min_id=None, progress_msg=None):
        """
        배치 처리 최적화 + Forum Topics 지원
        - 일반 채널: 50개씩 배치 전송 (100배 빠름)
        - Forum 채널: 개별 전송 (토픽 매핑 정확성 우선)
        """
        count = 0

        # Forum인 경우 토픽 동기화 먼저 수행
        is_forum = await self._is_forum(self.source)
        if is_forum:
            await self.log("Forum 감지! 토픽 동기화 시작...", "INFO")
            await self._sync_forum_topics()
            # Forum은 개별 전송 (토픽 매핑 필요)
            return await self._copy_all_individual(min_id, progress_msg)

        # 일반 채널: 배치 처리
        batch = []  # Message 객체 리스트
        batch_ids = []  # 메시지 ID 리스트

        async for msg in self.client.iter_messages(self.source, min_id=min_id, reverse=True):
            batch.append(msg)
            batch_ids.append(msg.id)

            # 배치가 BATCH_SIZE에 도달하면 전송
            if len(batch) >= BATCH_SIZE:
                count += await self._send_batch(batch, batch_ids, progress_msg, count)
                batch = []
                batch_ids = []
                await asyncio.sleep(0.5)  # FloodWait 방지

        # 남은 메시지 처리
        if batch:
            count += await self._send_batch(batch, batch_ids, progress_msg, count)

        return count

    async def _send_batch(self, batch, batch_ids, progress_msg, current_count):
        """배치 메시지 전송 및 매핑 저장"""
        try:
            # 배치 전송
            results = await self.client.forward_messages(
                self.target,
                batch_ids,
                self.source,
                drop_author=True
            )

            # 메시지 ID 매핑 저장 - DB에 영구 저장
            # results는 단일 Message or Message 리스트
            if results:
                if isinstance(results, list):
                    if results:  # 빈 리스트 체크
                        # 크기 불일치 경고
                        if len(batch) != len(results):
                            logger.warning(
                                f"⚠️ 배치 크기 불일치: 전송 {len(batch)}개, 수신 {len(results)}개"
                            )

                        # 안전하게 최소 길이만큼만 매핑
                        min_len = min(len(batch), len(results))
                        for i in range(min_len):
                            await self._save_mapping(batch[i].id, results[i].id)
                    else:
                        logger.warning("⚠️ forward_messages returned empty list")
                else:
                    # 단일 메시지인 경우
                    await self._save_mapping(batch[0].id, results.id)
            else:
                logger.warning("⚠️ forward_messages returned None")

            # 진행률 표시
            if progress_msg:
                new_count = current_count + len(batch)
                if new_count % 50 == 0 or new_count < 50:
                    try:
                        await progress_msg.edit(f"📤 복사 중... {new_count}개 (배치 처리)")
                    except Exception as edit_ex:
                        logger.warning(f"진행률 업데이트 실패 (무시): {edit_ex}")
                        # progress_msg를 None으로 설정할 수 없음 (함수 파라미터)
                        pass

            return len(batch)

        except FloodWaitError as e:
            logger.warning(f"⏰ FloodWait {e.seconds}초 대기 중...")
            await self.log(f"FloodWait 대기: {e.seconds}초", "WARNING")
            await asyncio.sleep(e.seconds)
            # 재시도
            try:
                results = await self.client.forward_messages(
                    self.target, batch_ids, self.source, drop_author=True
                )
                # 매핑 저장 - DB에 영구 저장
                if results:
                    if isinstance(results, list):
                        if results:  # 빈 리스트 체크
                            # 크기 불일치 경고
                            if len(batch) != len(results):
                                logger.warning(
                                    f"⚠️ 재시도 후 배치 크기 불일치: 전송 {len(batch)}개, 수신 {len(results)}개"
                                )

                            # 안전하게 최소 길이만큼만 매핑
                            min_len = min(len(batch), len(results))
                            for i in range(min_len):
                                await self._save_mapping(batch[i].id, results[i].id)
                        else:
                            logger.warning("⚠️ 재시도 후 빈 리스트 반환")
                    else:
                        await self._save_mapping(batch[0].id, results.id)
                else:
                    logger.warning("⚠️ 재시도 후 None 반환")
                return len(batch)
            except MessageIdInvalidError:
                logger.warning("⚠️ 재시도 실패: 메시지 삭제됨")
                return 0
            except ChatWriteForbiddenError:
                logger.error("❌ 재시도 실패: 쓰기 권한 없음")
                raise
            except Exception as retry_ex:
                logger.error(f"❌ 재시도 실패: {retry_ex}")
                raise

        except Exception as e:
            logger.error(f"❌ 배치 전송 실패, 개별 전송으로 전환: {e}")
            # 배치 실패 시 개별 전송으로 폴백
            sent_count = 0
            for msg in batch:
                try:
                    result = await self.client.forward_messages(
                        self.target, msg.id, self.source, drop_author=True
                    )
                    if result:
                        if hasattr(result, 'id'):
                            target_id = result.id
                        elif isinstance(result, list) and result:
                            target_id = result[0].id
                        else:
                            logger.warning(f"⚠️ Unexpected result type for msg #{msg.id}")
                            continue

                        await self._save_mapping(msg.id, target_id)
                        sent_count += 1
                except MessageIdInvalidError:
                    logger.warning(f"⚠️ 메시지 #{msg.id} 건너뜀")
                except Exception as ex:
                    logger.error(f"❌ 메시지 #{msg.id} 전송 실패: {ex}")
            return sent_count

    async def _copy_all_individual(self, min_id=None, progress_msg=None):
        """개별 메시지 전송 (Forum 채널용)"""
        count = 0

        async for msg in self.client.iter_messages(self.source, min_id=min_id, reverse=True):
            try:
                # 메시지가 토픽에 속한 경우 처리 (올바른 topic_id 추출)
                topic_id = None
                if hasattr(msg, 'reply_to') and msg.reply_to:
                    topic_id = getattr(msg.reply_to, 'reply_to_top_id', None)

                target_topic_id = None
                if topic_id and self.topic_mapping:
                    target_topic_id = self.topic_mapping.get(topic_id)

                # 전송 (Forum 토픽에 전송 시 reply_to 파라미터 사용)
                if target_topic_id:
                    result = await self.client.forward_messages(
                        self.target,
                        msg.id,
                        self.source,
                        drop_author=True,
                        reply_to=target_topic_id  # Forum 토픽으로 전송
                    )
                else:
                    result = await self.client.forward_messages(
                        self.target,
                        msg.id,
                        self.source,
                        drop_author=True
                    )

                # 메시지 ID 매핑 저장 - DB에 영구 저장
                if result:
                    if hasattr(result, 'id'):
                        target_id = result.id
                    elif isinstance(result, list) and result:
                        target_id = result[0].id
                    else:
                        logger.warning(f"⚠️ Unexpected result type for msg #{msg.id}")
                        continue

                    await self._save_mapping(msg.id, target_id)
                    count += 1  # 매핑 저장 성공 시에만 count 증가

                    if target_topic_id:
                        logger.debug(f"토픽 메시지 복사: #{msg.id} → 토픽 #{target_topic_id}")
                else:
                    logger.warning(f"⚠️ forward_messages returned None for msg #{msg.id}")

                # 진행률 표시
                if progress_msg and count % 50 == 0:
                    try:
                        await progress_msg.edit(f"📤 복사 중... {count}개 (Forum)")
                    except Exception as edit_ex:
                        logger.warning(f"진행률 업데이트 실패 (무시): {edit_ex}")
                        progress_msg = None  # 더 이상 업데이트 시도 안함

            except FloodWaitError as e:
                logger.warning(f"⏰ FloodWait {e.seconds}초 대기 중...")
                await asyncio.sleep(e.seconds)
                try:
                    # FloodWait 재시도 시에도 target_topic_id 사용
                    if target_topic_id:
                        result = await self.client.forward_messages(
                            self.target, msg.id, self.source, drop_author=True, reply_to=target_topic_id
                        )
                    else:
                        result = await self.client.forward_messages(
                            self.target, msg.id, self.source, drop_author=True
                        )
                    if result:
                        if hasattr(result, 'id'):
                            target_id = result.id
                        elif isinstance(result, list) and result:
                            target_id = result[0].id
                        else:
                            logger.warning(f"⚠️ 재시도 후 예상치 못한 타입: msg #{msg.id}")
                            continue

                        await self._save_mapping(msg.id, target_id)
                        count += 1  # 재시도 성공 시에도 count 증가
                except Exception as retry_ex:
                    logger.error(f"❌ FloodWait 재시도 실패 (msg #{msg.id}): {retry_ex}")
            except MessageIdInvalidError:
                logger.warning(f"⚠️ 메시지 #{msg.id} 건너뜀")
            except ChatWriteForbiddenError:
                logger.error("❌ 타겟 채널 쓰기 권한 없음!")
                await self.log("타겟 채널 쓰기 권한 없음", "ERROR")
                raise
            except ChannelPrivateError:
                logger.error("❌ 소스 채널 접근 권한 없음!")
                await self.log("소스 채널 접근 권한 없음", "ERROR")
                raise

        return count

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
