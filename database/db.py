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

        # message_mappings 테이블 (메시지 ID 매핑 - 편집/삭제 동기화용)
        # Bug #3 수정: 메모리 대신 DB에 영구 저장
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                source_chat_id TEXT NOT NULL,
                target_chat_id TEXT NOT NULL,
                source_msg_id INTEGER NOT NULL,
                target_msg_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES workers(id),
                UNIQUE(worker_id, source_chat_id, source_msg_id)
            )
        """)

        # message_mappings 인덱스 (빠른 조회를 위해)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_mappings_lookup
            ON message_mappings(worker_id, source_chat_id, source_msg_id)
        """)

        # mirrors 테이블에 last_synced_message_id 컬럼 추가 (중복 방지용)
        # Bug #2 수정: 이미 복사된 메시지 추적
        try:
            await db.execute("""
                ALTER TABLE mirrors ADD COLUMN last_synced_message_id INTEGER
            """)
        except:
            # 컬럼이 이미 존재하면 무시
            pass

        await db.commit()

async def get_db():
    """데이터베이스 연결 반환"""
    return await aiosqlite.connect(DATABASE_PATH)
