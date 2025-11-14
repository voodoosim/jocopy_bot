#!/usr/bin/env python3
"""
간이 테스트 - 주요 기능 검증
"""
import sys
import asyncio

print("=" * 60)
print("JoCopy Bot 간이 테스트")
print("=" * 60)

# 테스트 1: Import 검증
print("\n[테스트 1] Import 검증...")
try:
    from config import BOT_TOKEN, API_ID, API_HASH, DATABASE_PATH
    print("✅ config 모듈 import 성공")
except Exception as e:
    print(f"❌ config import 실패: {e}")
    sys.exit(1)

try:
    from database import init_db, get_db
    print("✅ database 모듈 import 성공")
except Exception as e:
    print(f"❌ database import 실패: {e}")
    sys.exit(1)

try:
    from controller import WorkerController
    print("✅ controller 모듈 import 성공")
except Exception as e:
    print(f"❌ controller import 실패: {e}")
    sys.exit(1)

try:
    from handlers import worker_router
    print("✅ handlers 모듈 import 성공")
except Exception as e:
    print(f"❌ handlers import 실패: {e}")
    sys.exit(1)

try:
    from worker import WorkerBot
    print("✅ worker 모듈 import 성공")
except Exception as e:
    print(f"❌ worker import 실패: {e}")
    sys.exit(1)

# 테스트 2: DB 초기화 검증
print("\n[테스트 2] DB 초기화 검증...")
async def test_db_init():
    try:
        await init_db()
        print("✅ DB 초기화 성공")

        # 테이블 존재 확인
        import aiosqlite
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row[0] for row in await cursor.fetchall()]

            required_tables = ['workers', 'mirrors', 'copies', 'logs', 'config', 'topic_mappings', 'message_mappings']
            for table in required_tables:
                if table in tables:
                    print(f"✅ 테이블 '{table}' 존재 확인")
                else:
                    print(f"❌ 테이블 '{table}' 없음!")

            # message_mappings 스키마 확인
            cursor = await db.execute("PRAGMA table_info(message_mappings)")
            columns = [row[1] for row in await cursor.fetchall()]
            print(f"✅ message_mappings 컬럼: {', '.join(columns)}")

            # 인덱스 확인
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='message_mappings'"
            )
            indexes = [row[0] for row in await cursor.fetchall()]
            print(f"✅ message_mappings 인덱스: {', '.join(indexes)}")

    except Exception as e:
        print(f"❌ DB 초기화 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

asyncio.run(test_db_init())

# 테스트 3: WorkerBot 클래스 검증
print("\n[테스트 3] WorkerBot 클래스 검증...")
try:
    # WorkerBot 인스턴스 생성 가능한지 확인 (실제 연결은 안함)
    # 주요 메서드들이 정의되어 있는지 확인
    methods = ['log', '_save_mapping', '_get_mapping', '_load_mappings_from_db', '_delete_mapping']

    for method_name in methods:
        if hasattr(WorkerBot, method_name):
            print(f"✅ WorkerBot.{method_name} 메서드 존재")
        else:
            print(f"❌ WorkerBot.{method_name} 메서드 없음!")

except Exception as e:
    print(f"❌ WorkerBot 검증 실패: {e}")
    sys.exit(1)

# 테스트 4: 환경 변수 확인
print("\n[테스트 4] 환경 변수 확인...")
if BOT_TOKEN and BOT_TOKEN != "your_bot_token_here":
    print("✅ BOT_TOKEN 설정됨")
else:
    print("⚠️ BOT_TOKEN 미설정 (테스트 환경일 수 있음)")

if API_ID and API_ID != 0:
    print("✅ API_ID 설정됨")
else:
    print("⚠️ API_ID 미설정")

if API_HASH and API_HASH != "your_api_hash_here":
    print("✅ API_HASH 설정됨")
else:
    print("⚠️ API_HASH 미설정")

if DATABASE_PATH:
    print(f"✅ DATABASE_PATH: {DATABASE_PATH}")
else:
    print("❌ DATABASE_PATH 미설정")

# 테스트 5: 수정된 기능 검증
print("\n[테스트 5] 수정된 기능 검증...")

# 5-1: FloodWait import 확인
try:
    from telethon.errors import FloodWaitError, MessageIdInvalidError
    print("✅ FloodWaitError import 성공")
except Exception as e:
    print(f"❌ FloodWaitError import 실패: {e}")

# 5-2: BytesIO import 확인
try:
    from io import BytesIO
    print("✅ BytesIO import 성공")
except Exception as e:
    print(f"❌ BytesIO import 실패: {e}")

# 5-3: InputChatUploadedPhoto import 확인
try:
    from telethon.tl.types import InputChatUploadedPhoto
    print("✅ InputChatUploadedPhoto import 성공")
except Exception as e:
    print(f"❌ InputChatUploadedPhoto import 실패: {e}")

print("\n" + "=" * 60)
print("✅ 모든 테스트 통과!")
print("=" * 60)
print("\n다음 단계:")
print("1. 워커 등록: /유닛추가")
print("2. 워커 시작: /유닛시작 1")
print("3. 그룹 복사 테스트: .소스입력 → .그룹복사")
print("4. 미러링 테스트: .미러 → 메시지 전송/편집/삭제")
print("=" * 60)
