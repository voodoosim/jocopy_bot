"""SQLite 데이터베이스 관리"""
import aiosqlite
from config import DATABASE_PATH

async def init_db():
    """데이터베이스 초기화 및 테이블 생성"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # workers 테이블
        await db.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                session_string TEXT NOT NULL,
                phone TEXT,
                log_channel_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP,
                status TEXT DEFAULT 'stopped',
                process_id INTEGER
            )
        """)

        # mirrors 테이블 (미러링 모드)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mirrors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                source_chat TEXT NOT NULL,
                target_chat TEXT NOT NULL,
                mode TEXT DEFAULT 'mirror',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_message_id INTEGER,
                status TEXT DEFAULT 'active',
                FOREIGN KEY (worker_id) REFERENCES workers(id)
            )
        """)

        # copies 테이블 (복사 모드)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS copies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                source_chat TEXT NOT NULL,
                target_chat TEXT NOT NULL,
                mode TEXT DEFAULT 'copy',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_messages INTEGER,
                copied_messages INTEGER DEFAULT 0,
                last_message_id INTEGER,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY (worker_id) REFERENCES workers(id)
            )
        """)

        # logs 테이블 (중앙 집중식 로그)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                worker_name TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent BOOLEAN DEFAULT 0,
                FOREIGN KEY (worker_id) REFERENCES workers(id)
            )
        """)

        # config 테이블 (전역 설정)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # topic_mappings 테이블 (Forum 토픽 매핑)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS topic_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                source_chat_id TEXT NOT NULL,
                target_chat_id TEXT NOT NULL,
                source_topic_id INTEGER NOT NULL,
                target_topic_id INTEGER NOT NULL,
                topic_title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES workers(id),
                UNIQUE(worker_id, source_chat_id, source_topic_id)
            )
        """)

        await db.commit()

async def get_db():
    """데이터베이스 연결 반환"""
    return await aiosqlite.connect(DATABASE_PATH)
