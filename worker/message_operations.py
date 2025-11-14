"""Message Copy Operations (Batch + Individual)"""
import logging
import asyncio
from typing import Optional, Any, Callable, Dict
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    MessageIdInvalidError,
    ChatWriteForbiddenError,
    ChannelPrivateError
)
from config import BATCH_SIZE

logger = logging.getLogger(__name__)


class MessageCopyOperations:
    """메시지 복사 작업 (배치 처리 + 개별 전송)"""

    def __init__(
        self,
        client: TelegramClient,
        mapping_manager: Any,  # MessageMappingManager
        forum_manager: Any,  # ForumTopicManager
        log_callback: Callable[[str, str], Any]
    ):
        """
        Args:
            client: Telethon TelegramClient 인스턴스
            mapping_manager: MessageMappingManager 인스턴스
            forum_manager: ForumTopicManager 인스턴스
            log_callback: async def log(msg, level) 로깅 콜백
        """
        self.client = client
        self.mapping_manager = mapping_manager
        self.forum_manager = forum_manager
        self.log = log_callback  # async def log(msg, level)

    async def copy_all(
        self,
        source: Any,
        target: Any,
        min_id: Optional[int] = None,
        progress_msg: Optional[Any] = None
    ) -> int:
        """
        배치 처리 최적화 + Forum Topics 지원
        - 일반 채널: BATCH_SIZE개씩 배치 전송 (100배 빠름)
        - Forum 채널: 개별 전송 (토픽 매핑 정확성 우선)

        Args:
            source: 소스 채널/그룹 entity
            target: 타겟 채널/그룹 entity
            min_id: 시작할 최소 메시지 ID (None이면 처음부터)
            progress_msg: 진행률 표시용 메시지 객체 (optional)

        Returns:
            복사된 메시지 수
        """
        count = 0

        # Forum인 경우 토픽 동기화 먼저 수행
        is_forum = await self.forum_manager.is_forum(source)
        if is_forum:
            await self.log("Forum 감지! 토픽 동기화 시작...", "INFO")
            await self.forum_manager.sync_forum_topics(source, target)
            # Forum은 개별 전송 (토픽 매핑 필요)
            return await self._copy_all_individual(source, target, min_id, progress_msg)

        # 일반 채널: 배치 처리
        batch = []  # Message 객체 리스트
        batch_ids = []  # 메시지 ID 리스트

        async for msg in self.client.iter_messages(source, min_id=min_id, reverse=True):
            batch.append(msg)
            batch_ids.append(msg.id)

            # 배치가 BATCH_SIZE에 도달하면 전송
            if len(batch) >= BATCH_SIZE:
                count += await self._send_batch(source, target, batch, batch_ids, progress_msg, count)
                batch = []
                batch_ids = []
                await asyncio.sleep(0.5)  # FloodWait 방지

        # 남은 메시지 처리
        if batch:
            count += await self._send_batch(source, target, batch, batch_ids, progress_msg, count)

        return count

    async def _send_batch(
        self,
        source: Any,
        target: Any,
        batch: list,
        batch_ids: list,
        progress_msg: Optional[Any],
        current_count: int
    ) -> int:
        """
        배치 메시지 전송 및 매핑 저장

        Args:
            source: 소스 채널/그룹 entity
            target: 타겟 채널/그룹 entity
            batch: Message 객체 리스트
            batch_ids: 메시지 ID 리스트
            progress_msg: 진행률 표시용 메시지 객체
            current_count: 현재까지 복사된 메시지 수

        Returns:
            이번 배치에서 복사된 메시지 수
        """
        try:
            # 배치 전송
            results = await self.client.forward_messages(
                target,
                batch_ids,
                source,
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
                            await self.mapping_manager.save_mapping(
                                source,
                                target,
                                batch[i].id,
                                results[i].id
                            )
                    else:
                        logger.warning("⚠️ forward_messages returned empty list")
                else:
                    # 단일 메시지인 경우
                    await self.mapping_manager.save_mapping(
                        source,
                        target,
                        batch[0].id,
                        results.id
                    )
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
                    target, batch_ids, source, drop_author=True
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
                                await self.mapping_manager.save_mapping(
                                    source,
                                    target,
                                    batch[i].id,
                                    results[i].id
                                )
                        else:
                            logger.warning("⚠️ 재시도 후 빈 리스트 반환")
                    else:
                        await self.mapping_manager.save_mapping(
                            source,
                            target,
                            batch[0].id,
                            results.id
                        )
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
                        target, msg.id, source, drop_author=True
                    )
                    if result:
                        if hasattr(result, 'id'):
                            target_id = result.id
                        elif isinstance(result, list) and result:
                            target_id = result[0].id
                        else:
                            logger.warning(f"⚠️ Unexpected result type for msg #{msg.id}")
                            continue

                        await self.mapping_manager.save_mapping(
                            source,
                            target,
                            msg.id,
                            target_id
                        )
                        sent_count += 1
                except MessageIdInvalidError:
                    logger.warning(f"⚠️ 메시지 #{msg.id} 건너뜀")
                except Exception as ex:
                    logger.error(f"❌ 메시지 #{msg.id} 전송 실패: {ex}")
            return sent_count

    async def _copy_all_individual(
        self,
        source: Any,
        target: Any,
        min_id: Optional[int] = None,
        progress_msg: Optional[Any] = None
    ) -> int:
        """
        개별 메시지 전송 (Forum 채널용)

        Args:
            source: 소스 채널/그룹 entity
            target: 타겟 채널/그룹 entity
            min_id: 시작할 최소 메시지 ID (None이면 처음부터)
            progress_msg: 진행률 표시용 메시지 객체 (optional)

        Returns:
            복사된 메시지 수
        """
        count = 0

        async for msg in self.client.iter_messages(source, min_id=min_id, reverse=True):
            try:
                # 메시지가 토픽에 속한 경우 처리 (올바른 topic_id 추출)
                topic_id = None
                if hasattr(msg, 'reply_to') and msg.reply_to:
                    topic_id = getattr(msg.reply_to, 'reply_to_top_id', None)

                target_topic_id = None
                if topic_id and self.forum_manager.topic_mapping:
                    target_topic_id = self.forum_manager.topic_mapping.get(topic_id)

                # 전송 (Forum 토픽에 전송 시 reply_to 파라미터 사용)
                if target_topic_id:
                    result = await self.client.forward_messages(
                        target,
                        msg.id,
                        source,
                        drop_author=True,
                        reply_to=target_topic_id  # Forum 토픽으로 전송
                    )
                else:
                    result = await self.client.forward_messages(
                        target,
                        msg.id,
                        source,
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

                    await self.mapping_manager.save_mapping(
                        source,
                        target,
                        msg.id,
                        target_id
                    )
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
                            target, msg.id, source, drop_author=True, reply_to=target_topic_id
                        )
                    else:
                        result = await self.client.forward_messages(
                            target, msg.id, source, drop_author=True
                        )
                    if result:
                        if hasattr(result, 'id'):
                            target_id = result.id
                        elif isinstance(result, list) and result:
                            target_id = result[0].id
                        else:
                            logger.warning(f"⚠️ 재시도 후 예상치 못한 타입: msg #{msg.id}")
                            continue

                        await self.mapping_manager.save_mapping(
                            source,
                            target,
                            msg.id,
                            target_id
                        )
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
            except Exception as e:
                logger.error(f"❌ 메시지 #{msg.id} 복사 실패: {e}")

        return count
