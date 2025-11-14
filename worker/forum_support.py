"""Forum Topics Support

Forum 채널의 토픽 동기화 및 매핑 관리를 담당하는 모듈입니다.

주요 기능:
- Forum 채널 감지
- 토픽 목록 조회
- 타겟 채널에 동일한 토픽 생성
- 소스-타겟 토픽 매핑 생성 및 DB 저장

사용 예시:
    forum_mgr = ForumTopicManager(client, worker_id, worker_name)
    is_forum = await forum_mgr.is_forum(source_chat)
    if is_forum:
        mapping = await forum_mgr.sync_forum_topics(source_chat, target_chat)
"""
import logging
import aiosqlite
from typing import Dict, Optional
from telethon import TelegramClient
from telethon.tl.functions.channels import (
    CreateForumTopicRequest,
    GetForumTopicsRequest,
)

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


class ForumTopicManager:
    """Forum 토픽 동기화 관리자

    Telegram Forum 채널의 토픽 구조를 소스에서 타겟으로 복사하고,
    소스 토픽 ID와 타겟 토픽 ID 간의 매핑을 생성 및 관리합니다.

    Attributes:
        client: Telethon TelegramClient 인스턴스
        worker_id: Worker Bot의 고유 ID
        worker_name: Worker Bot의 이름
        topic_mapping: 소스 토픽 ID → 타겟 토픽 ID 매핑 (Dict[int, int])
    """

    def __init__(self, client: TelegramClient, worker_id: int, worker_name: str):
        """ForumTopicManager 초기화

        Args:
            client: Telethon TelegramClient 인스턴스
            worker_id: Worker Bot의 고유 ID (DB 저장용)
            worker_name: Worker Bot의 이름 (로깅용)
        """
        self.client = client
        self.worker_id = worker_id
        self.worker_name = worker_name
        self.topic_mapping: Dict[int, int] = {}  # source_topic_id → target_topic_id

    async def is_forum(self, chat) -> bool:
        """채널이 Forum인지 확인

        Args:
            chat: 확인할 채널/채팅 엔티티

        Returns:
            bool: Forum 채널이면 True, 아니면 False

        Example:
            >>> if await forum_mgr.is_forum(source_chat):
            ...     print("Forum 감지!")
        """
        try:
            entity = await self.client.get_entity(chat)
            return getattr(entity, 'forum', False)
        except Exception as e:
            logger.error(f"Forum 확인 실패: {e}")
            return False

    async def get_forum_topics(self, chat) -> list:
        """Forum의 모든 토픽 가져오기

        Args:
            chat: Forum 채널 엔티티

        Returns:
            list: 토픽 객체 리스트 (각 토픽은 id, title, icon_color 등 포함)

        Note:
            - 최대 100개 토픽까지 조회
            - 실패 시 빈 리스트 반환
        """
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

    async def create_matching_topic(
        self,
        target: any,
        title: str,
        icon_color: int = None,
        icon_emoji_id: int = None
    ) -> Optional[int]:
        """타겟에 동일한 토픽 생성

        Args:
            target: 타겟 Forum 채널 엔티티
            title: 생성할 토픽 제목
            icon_color: 토픽 아이콘 색상 (선택적, 기본값: 파란색 0x6FB9F0)
            icon_emoji_id: 토픽 이모지 ID (선택적)

        Returns:
            Optional[int]: 생성된 토픽 ID (실패 시 None)

        Note:
            - 생성된 토픽 ID는 result.updates[0].message.reply_to.reply_to_top_id에서 추출
            - 이 ID는 메시지 전송 시 reply_to 파라미터로 사용
        """
        try:
            result = await self.client(CreateForumTopicRequest(
                channel=target,
                title=title,
                icon_color=icon_color or 0x6FB9F0,  # 기본 파란색
                icon_emoji_id=icon_emoji_id or 0
            ))
            # 생성된 토픽 ID 반환 (reply_to_top_id 사용)
            # FIXED: 올바른 토픽 ID 추출 방법
            if result.updates and result.updates[0].message:
                msg = result.updates[0].message
                if hasattr(msg, 'reply_to') and msg.reply_to:
                    return getattr(msg.reply_to, 'reply_to_top_id', None)
            return None
        except Exception as e:
            logger.error(f"토픽 생성 실패 ({title}): {e}")
            return None

    async def sync_forum_topics(self, source: any, target: any) -> dict:
        """소스와 타겟의 토픽 동기화 및 매핑 생성

        소스 Forum 채널의 모든 토픽을 타겟 Forum 채널에 복사하고,
        소스 토픽 ID와 타겟 토픽 ID 간의 매핑을 생성합니다.

        Args:
            source: 소스 Forum 채널 엔티티
            target: 타겟 Forum 채널 엔티티

        Returns:
            dict: 소스 토픽 ID → 타겟 토픽 ID 매핑 (Dict[int, int])

        Example:
            >>> mapping = await forum_mgr.sync_forum_topics(source, target)
            >>> print(f"동기화된 토픽: {len(mapping)}개")
            >>> # mapping = {1234: 5678, 1235: 5679, ...}

        Note:
            - 매핑은 메모리(self.topic_mapping)와 DB(topic_mappings 테이블)에 모두 저장
            - 각 토픽 생성 시 SUCCESS/ERROR 로그 생성
            - 소스에 토픽이 없으면 빈 dict 반환
        """
        mapping = {}

        # 소스 토픽 가져오기
        source_topics = await self.get_forum_topics(source)
        if not source_topics:
            logger.info("소스에 토픽 없음 (일반 채널)")
            return mapping

        await self.log(f"Forum 토픽 동기화 시작: {len(source_topics)}개", "INFO")

        # 각 토픽 복사
        for topic in source_topics:
            source_topic_id = topic.id
            topic_title = topic.title

            # 타겟에 동일한 토픽 생성
            target_topic_id = await self.create_matching_topic(
                target=target,
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
                                str(source.id if hasattr(source, 'id') else source),
                                str(target.id if hasattr(target, 'id') else target),
                                source_topic_id,
                                target_topic_id,
                                topic_title
                            )
                        )
                        await db.commit()
                except Exception as e:
                    logger.error(f"토픽 매핑 DB 저장 실패: {e}")

                await self.log(
                    f"토픽 생성 완료: {topic_title} (소스 #{source_topic_id} → 타겟 #{target_topic_id})",
                    "SUCCESS"
                )
            else:
                await self.log(f"토픽 생성 실패: {topic_title}", "ERROR")

        self.topic_mapping = mapping
        await self.log(f"Forum 토픽 동기화 완료: {len(mapping)}개", "SUCCESS")
        return mapping

    async def log(self, message: str, level: str = "INFO"):
        """로그를 DB에 저장

        Args:
            message: 로그 메시지
            level: 로그 레벨 (INFO, SUCCESS, WARNING, ERROR 등)

        Note:
            - logs 테이블에 저장
            - Manager Bot이 나중에 log_channel로 전송
            - 저장 실패 시 logger.error로 로깅 (무한 재귀 방지)
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
