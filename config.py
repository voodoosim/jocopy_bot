"""JoCopy Bot 설정 - 팀 규모 최적화"""
import os
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

# Main Bot 설정
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN이 설정되지 않았습니다. .env 파일을 확인하세요.")

# Telegram API 설정 (Worker용)
API_ID = int(os.getenv("API_ID", "0"))  # Telethon은 정수 필요!
API_HASH = os.getenv("API_HASH", "")

# 로그 채널 설정 (전역)
LOG_CHANNEL_ID = None  # /로그채널설정 명령으로 설정

# Database 설정
DATABASE_PATH = os.getenv("DATABASE_PATH", "./jocopy.db")

# 로깅 설정
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ===================================================================
# 팀 규모 최적화 설정 (100명 팀, 16GB RAM 기준)
# ===================================================================

# 워커 제한
MAX_REGISTERED_WORKERS = 100        # 최대 등록 워커 수
MAX_ACTIVE_WORKERS = 20             # 동시 활성 워커 수
MAX_CONCURRENT_TASKS = 10           # 동시 작업 수

# 워커 리소스 관리
WORKER_MEMORY_LIMIT_MB = 80         # 워커당 메모리 제한
WORKER_IDLE_TIMEOUT_SEC = 1800      # 유휴 시 종료 (30분)
WORKER_MAX_LIFETIME_SEC = 86400     # 최대 생존 시간 (24시간)

# 복사/미러링 성능 최적화
BATCH_SIZE = 100                    # 배치 처리 크기
MAX_RETRIES = 3                     # 재시도 횟수
RETRY_DELAY_SEC = 5                 # 재시도 대기 시간
FLOODWAIT_THRESHOLD_SEC = 60        # FloodWait 임계값

# 진행률 업데이트
PROGRESS_UPDATE_INTERVAL = 50       # N개마다 진행률 표시
STATUS_UPDATE_INTERVAL_SEC = 30     # 상태 업데이트 주기

# 캐시 설정
CHANNEL_CACHE_SIZE = 100            # 채널 정보 캐시
MESSAGE_CACHE_SIZE = 1000           # 메시지 캐시

# 세션 관리
SESSION_VALIDATION_TIMEOUT = 10     # 세션 검증 타임아웃
SESSION_RECONNECT_DELAY = 5         # 재연결 대기 시간

# 로깅
LOG_FILE = "./logs/jocopy.log"      # 로그 파일 경로
LOG_MAX_SIZE_MB = 10                # 로그 파일 최대 크기
LOG_BACKUP_COUNT = 5                # 로그 백업 개수
