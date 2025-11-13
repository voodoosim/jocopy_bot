"""JoCopy Bot - Main Bot"""
import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, LOG_LEVEL, DATABASE_PATH
from database import init_db, get_db
from handlers import worker_router

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 로그 레벨별 이모지
LOG_EMOJI = {
    "INFO": "ℹ️",
    "SUCCESS": "✅",
    "WARNING": "⚠️",
    "ERROR": "❌",
    "START": "🚀",
    "STOP": "🛑"
}

async def poll_logs(bot: Bot):
    """로그 폴링 백그라운드 태스크"""
    logger.info("📊 로그 폴링 시작...")

    while True:
        try:
            # 로그 채널 ID 가져오기
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT value FROM config WHERE key = 'log_channel_id'"
                ) as cursor:
                    result = await cursor.fetchone()
                    log_channel_id = result[0] if result else None

            # 로그 채널이 설정되지 않았으면 대기
            if not log_channel_id:
                await asyncio.sleep(5)
                continue

            # 전송되지 않은 로그 가져오기
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    """
                    SELECT id, worker_name, level, message
                    FROM logs
                    WHERE sent = 0
                    ORDER BY created_at ASC
                    LIMIT 10
                    """
                ) as cursor:
                    logs = await cursor.fetchall()

            # 로그 전송
            for log_id, worker_name, level, message in logs:
                emoji = LOG_EMOJI.get(level, "📝")
                text = f"{emoji} **[{worker_name}]** {message}"

                try:
                    await bot.send_message(log_channel_id, text)

                    # sent 플래그 업데이트
                    async with aiosqlite.connect(DATABASE_PATH) as db:
                        await db.execute(
                            "UPDATE logs SET sent = 1 WHERE id = ?",
                            (log_id,)
                        )
                        await db.commit()

                except Exception as e:
                    logger.error(f"로그 전송 실패 (ID: {log_id}): {e}")
                    # 전송 실패 시에도 계속 진행 (다음 폴링에서 재시도)

            # 2초 대기
            await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"로그 폴링 오류: {e}")
            await asyncio.sleep(5)

async def main():
    """메인 함수"""
    # 데이터베이스 초기화
    logger.info("데이터베이스 초기화 중...")
    await init_db()
    logger.info("✅ 데이터베이스 초기화 완료")

    # Bot 및 Dispatcher 생성
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # 핸들러 등록
    dp.include_router(worker_router)

    # 로그 폴링 백그라운드 태스크 시작
    log_task = asyncio.create_task(poll_logs(bot))

    # 봇 시작
    logger.info("🚀 JoCopy Bot 시작...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        # 백그라운드 태스크 종료
        log_task.cancel()
        try:
            await log_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 JoCopy Bot 종료")
