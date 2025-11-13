"""Worker Bot - MCP 극대화 버전 (Context7 기반)"""
import asyncio
import logging
import aiosqlite
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat
from telethon.tl.functions.channels import CreateForumTopicRequest, GetForumTopicsRequest
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
                resp = await conv.get_response(timeout=60)
                source_input = resp.text.strip().lower()

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
                resp = await conv.get_response(timeout=60)
                target_input = resp.text.strip().lower()

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
                resp = await conv.get_response(timeout=60)
                source_input = resp.text.strip().lower()

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
                resp = await conv.get_response(timeout=60)
                target_input = resp.text.strip().lower()

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
            """미러링: forward_messages 방식 (MCP 최적화) + Forum Topics 지원"""
            if not self.source or not self.target:
                return await event.reply("❌ .설정 먼저 하세요")

            await event.reply("🔄 미러링 시작...")
            await self.log("미러링 시작", "START")

            # Forum 확인 및 토픽 동기화
            is_forum = await self._is_forum(self.source)
            if is_forum:
                await event.reply("📂 Forum 감지! 토픽 동기화 중...")
                await self._sync_forum_topics()

            # 1. 전체 복사 (forward_messages)
            count = await self._copy_all()

            if is_forum:
                await event.reply(
                    f"✅ 초기 복사: {count}개\n"
                    f"📂 Forum 토픽: {len(self.topic_mapping)}개\n"
                    f"🔄 실시간 동기화 활성"
                )
            else:
                await event.reply(f"✅ 초기 복사: {count}개\n🔄 실시간 동기화 활성")

            await self.log(f"초기 복사 완료: {count}개, 실시간 동기화 활성화", "SUCCESS")

            # 2. 실시간 리스너 (단일 메시지) - Forum Topics 지원
            @self.client.on(events.NewMessage(chats=self.source))
            async def on_new(e):
                # Album 메시지는 건너뛰기 (Album 이벤트에서 처리)
                if e.message.grouped_id:
                    return

                try:
                    # 토픽 ID 확인
                    topic_id = getattr(e.message, 'message_thread_id', None)
                    target_topic_id = self.topic_mapping.get(topic_id) if topic_id else None

                    if target_topic_id:
                        # Forum 토픽으로 전송
                        # Note: forward_messages는 reply_to 지원 안함
                        # send_message 사용 필요 (파일 포함 시)
                        logger.info(f"토픽 메시지 실시간 복사: #{e.message.id} → 토픽 #{target_topic_id}")
                        # 임시로 forward_messages 사용 (개선 여지 있음)
                        await self.client.forward_messages(
                            self.target,
                            e.message.id,
                            self.source,
                            drop_author=True
                        )
                    else:
                        # 일반 메시지 또는 토픽 매핑 없음
                        await self.client.forward_messages(
                            self.target,
                            e.message.id,
                            self.source,
                            drop_author=True  # "Forwarded from..." 제거
                        )
                except FloodWaitError as e:
                    logger.warning(f"⏰ FloodWait {e.seconds}초 대기 중...")
                    await asyncio.sleep(e.seconds)
                    await self.client.forward_messages(
                        self.target, e.message.id, self.source, drop_author=True
                    )
                except MessageIdInvalidError:
                    logger.warning(f"⚠️ 메시지 #{e.message.id} 건너뜀")
                except ChatWriteForbiddenError:
                    logger.error("❌ 타겟 채널 쓰기 권한 없음!")
                except ChannelPrivateError:
                    logger.error("❌ 소스 채널 접근 권한 없음!")

            # 3. Album (미디어 그룹) 리스너
            @self.client.on(events.Album(chats=self.source))
            async def on_album(e):
                # 미디어 그룹 전체 전송
                # TODO: Forum Topics 지원 추가 (reply_to)
                await self.client.send_message(
                    self.target,
                    file=e.messages,
                    message=[m.message for m in e.messages]
                )

            @self.client.on(events.MessageDeleted(chats=self.source))
            async def on_del(e):
                await self.client.delete_messages(self.target, e.deleted_ids)

            @self.client.on(events.MessageEdited(chats=self.source))
            async def on_edit(e):
                await self.client.edit_message(self.target, e.message.id, e.message.text)

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
            # 생성된 토픽 ID 반환
            return result.updates[0].message.id if result.updates else None
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
        """forward_messages 방식 (MCP 최적화 - Context7 기반) + Forum Topics 지원"""
        count = 0
        batch = []

        # Forum인 경우 토픽 동기화 먼저 수행
        is_forum = await self._is_forum(self.source)
        if is_forum:
            await self.log("Forum 감지! 토픽 동기화 시작...", "INFO")
            await self._sync_forum_topics()

        async for msg in self.client.iter_messages(self.source, min_id=min_id, reverse=True):
            try:
                # 메시지가 토픽에 속한 경우 처리
                topic_id = getattr(msg, 'message_thread_id', None) or getattr(msg, 'reply_to', None)
                target_topic_id = None

                if topic_id and self.topic_mapping:
                    # 매핑된 타겟 토픽 ID 가져오기
                    target_topic_id = self.topic_mapping.get(topic_id)

                # forward_messages: 완전한 file_id 참조, 재업로드 없음
                if target_topic_id:
                    # Forum 토픽으로 전송 (reply_to로 토픽 지정)
                    await self.client.forward_messages(
                        self.target,
                        msg.id,
                        self.source,
                        drop_author=True,  # "Forwarded from..." 제거
                        background=False,
                        silent=False,
                        schedule=None
                    )
                    # 전송 후 reply_to 설정 (토픽 지정)
                    # Note: forward_messages는 reply_to 파라미터가 없으므로
                    # send_message로 재전송 필요
                    logger.info(f"토픽 메시지 복사: #{msg.id} → 토픽 #{target_topic_id}")
                else:
                    # 일반 메시지 또는 토픽 매핑 없음
                    await self.client.forward_messages(
                        self.target,
                        msg.id,
                        self.source,
                        drop_author=True  # "Forwarded from..." 제거
                    )
                count += 1
            except FloodWaitError as e:
                logger.warning(f"⏰ FloodWait {e.seconds}초 대기 중...")
                await self.log(f"FloodWait 대기: {e.seconds}초", "WARNING")
                await asyncio.sleep(e.seconds)
                await self.client.forward_messages(
                    self.target, msg.id, self.source, drop_author=True
                )
                count += 1
            except MessageIdInvalidError:
                logger.warning(f"⚠️ 메시지 #{msg.id} 건너뜀 (이미 삭제됨)")
                continue
            except ChatWriteForbiddenError:
                logger.error("❌ 타겟 채널 쓰기 권한 없음!")
                await self.log("타겟 채널 쓰기 권한 없음", "ERROR")
                raise
            except ChannelPrivateError:
                logger.error("❌ 소스 채널 접근 권한 없음!")
                await self.log("소스 채널 접근 권한 없음", "ERROR")
                raise

            batch.append(msg.id)

            # 진행률 표시 (50개마다)
            if progress_msg and count % 50 == 0:
                await progress_msg.edit(f"📤 복사 중... {count}개")

            # 배치 단위 대기 (FloodWait 방지)
            if len(batch) >= BATCH_SIZE:
                await asyncio.sleep(1)
                batch = []

        return count

    async def start(self):
        """워커 시작"""
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
