# JoCopy Bot - Telegram Mirror Bot

> **버전**: v0.3.0  
> **상태**: 운영 준비  
> **아키텍처**: Manager-Worker (aiogram + Telethon)

텔레그램 채널/그룹 메시지 미러링 봇. Manager-Worker 패턴으로 무제한 계정 지원, 독립적인 소스/타겟 설정, 권한 자동 검증 기능 제공.

---

## ✨ 주요 기능

### Manager Bot (aiogram)
- 워커 계정 관리 (추가/시작/중지)
- 워커 상태 모니터링
- 로그 채널 연동
- 사용자 친화적 FSM 기반 UI

### Worker Bot (Telethon)
- `.소스입력` - 소스 채널/그룹 독립 설정 ⭐ 신규
- `.타겟입력` - 타겟 채널/그룹 독립 설정 + 권한 검증 ⭐ 신규
- `.설정` - 소스+타겟 한번에 설정 (기존)
- `.미러` - 실시간 미러링
- `.카피` - 전체 메시지 복사
- `.지정 <ID>` - 특정 메시지 ID부터 복사
- Forum Topics 완전 지원
- FloodWaitError 자동 처리

### 주요 개선 사항 (v0.3.0)
1. **독립적인 소스/타겟 설정**
   - `.소스입력`으로 소스만 변경 가능
   - `.타겟입력`으로 타겟만 변경 가능
   - 유연한 설정 워크플로우 지원

2. **직관적인 채널/그룹 구분**
   - `c1`, `c2` (채널)
   - `g1`, `g2` (그룹)
   - 명확한 입력 형식

3. **타겟 쓰기 권한 자동 검증**
   - 테스트 메시지 전송 후 즉시 삭제
   - 권한 없을 시 상세 해결 방법 안내

---

## 🚀 빠른 시작

### 1. 요구사항
- Python 3.10+
- Telegram Bot Token (Main Bot용)
- Telegram API ID & Hash (Worker용)
- StringSession (각 워커 계정)

### 2. 설치

```bash
git clone https://github.com/voodoosim/jocopy_bot.git
cd jocopy_bot
pip install aiogram telethon aiosqlite python-dotenv
```

### 3. 환경 설정

`.env` 파일 생성:

```env
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
API_ID=12345678
API_HASH=0123456789abcdef0123456789abcdef
DATABASE_PATH=./jocopy.db
LOG_LEVEL=INFO
```

### 4. 실행

```bash
python3 bot.py
```

---

## 📖 사용법

### Manager Bot (@JoCopy_bot)

#### 워커 추가
```
/유닛추가
→ 워커 이름 입력
→ StringSession 입력
```

#### 워커 시작
```
/유닛시작 1
```

#### 워커 목록
```
/유닛목록
```

### Worker Bot (Saved Messages)

#### 방법 1: 독립 설정 (신규)
```
.소스입력
→ c1 또는 g1 입력

.타겟입력
→ c2 또는 g2 입력
→ 권한 자동 검증

.미러
```

#### 방법 2: 통합 설정 (기존)
```
.설정
→ 소스: c1
→ 타겟: g2
→ 권한 자동 검증

.미러
```

---

## 🎯 사용 시나리오

### 시나리오 1: 첫 설정
```
.소스입력 → c1
.타겟입력 → g2
.미러
```

### 시나리오 2: 타겟만 변경
```
이미 소스 설정됨
.타겟입력 → c3 (새 타겟)
.미러
```

### 시나리오 3: 여러 타겟에 순차 복사
```
.소스입력 → c1
.타겟입력 → g1 → .카피
.타겟입력 → g2 → .카피
.타겟입력 → g3 → .카피
```

---

## 🏗️ 아키텍처

```
JoCopy Bot
├── bot.py                    # Main Bot (aiogram)
├── config.py                 # 설정
├── database/
│   └── db.py                 # DB 초기화
├── handlers/
│   └── worker_handlers.py    # Manager 핸들러
├── controller/
│   └── worker_controller.py  # 프로세스 관리
└── worker/
    └── worker_bot.py         # Worker 구현 (Telethon)
```

### 데이터베이스 (SQLite)
- `workers` - 워커 정보
- `mirrors` - 미러링 설정
- `copies` - 복사 작업
- `logs` - 중앙 로그
- `config` - 전역 설정
- `topic_mappings` - Forum 토픽 매핑

---

## 📝 명령어 참조

### Manager Bot 명령어

| 명령어 | 설명 |
|--------|------|
| `/시작`, `/start` | 메인 메뉴 |
| `/유닛추가` | 워커 추가 |
| `/유닛목록` | 워커 목록 |
| `/유닛시작 <ID>` | 워커 시작 |
| `/유닛중지 <ID>` | 워커 중지 |
| `/유닛재시작 <ID>` | 워커 재시작 |
| `/로그설정` | 로그 채널 설정 |
| `/상태` | 전체 상태 확인 |
| `/도움말` | 도움말 |

### Worker Bot 명령어 (Saved Messages)

| 명령어 | 설명 | 버전 |
|--------|------|------|
| `.소스입력` | 소스만 독립 설정 | v0.3.0 ⭐ |
| `.타겟입력` | 타겟만 독립 설정 + 권한 검증 | v0.3.0 ⭐ |
| `.설정` | 소스+타겟 통합 설정 | 기존 |
| `.목록` | 채널/그룹 목록 | |
| `.미러` | 실시간 미러링 시작 | |
| `.카피` | 전체 메시지 복사 | |
| `.지정 <ID>` | 메시지 ID부터 복사 | |

---

## 🔧 문제 해결

### 워커가 시작되지 않을 때

```bash
# DB 상태 리셋
python3 -c "
import asyncio
import aiosqlite

async def reset():
    async with aiosqlite.connect('./jocopy.db') as db:
        await db.execute('UPDATE workers SET status = \"stopped\", process_id = NULL')
        await db.commit()
        print('✅ DB 리셋 완료')

asyncio.run(reset())
"

# 워커 재시작
@JoCopy_bot: /유닛시작 1
```

### 권한 오류

`.타겟입력` 실행 시 "❌ 타겟 쓰기 권한 없음!" 발생:

1. 타겟 채널/그룹으로 이동
2. 워커 계정을 관리자로 추가
3. "메시지 게시" 권한 활성화
4. `.타겟입력` 다시 실행

### 캐시 문제

```bash
# 모든 프로세스 종료
ps aux | grep "python3 bot.py" | awk '{print $2}' | xargs -r kill -9

# 캐시 제거
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

# 재시작
python3 bot.py > bot.log 2>&1 &
```

---

## 📚 문서

- [빠른 시작 가이드](QUICK_START.md)
- [개발 로그](DEVELOPMENT_LOG.md) - 1,151줄 상세 문서
- [세션 재개 가이드](SESSION_RESUME.md)

---

## 🔒 보안

### 중요 파일 (.gitignore에 포함)
- `.env` - 토큰 및 API 키
- `*.session` - Telethon 세션 파일
- `jocopy.db` - 데이터베이스
- `bot.log` - 로그 파일

### 권장 사항
- 프로덕션 환경에서는 PostgreSQL 사용 권장
- `.env` 파일 절대 커밋하지 말 것
- StringSession은 안전하게 보관

---

## 📊 성능

- **메시지 복사 속도**: ~1-2 msg/sec
- **배치 처리**: 100개 단위
- **FloodWait 자동 처리**: Telegram API 제한 준수
- **메모리 사용**: 워커당 ~80MB
- **동시 활성 워커**: 최대 20개 (설정 가능)

---

## 🛠️ 기술 스택

- **Manager Bot**: aiogram 3.13.1
- **Worker Bot**: Telethon 1.41.2
- **Database**: SQLite (aiosqlite)
- **Async**: asyncio
- **Python**: 3.10+

---

## 📝 라이선스

MIT License

---

## 🤝 기여

Pull Request 환영합니다!

1. Fork
2. Feature 브랜치 생성 (`git checkout -b feature/AmazingFeature`)
3. 커밋 (`git commit -m 'Add some AmazingFeature'`)
4. Push (`git push origin feature/AmazingFeature`)
5. Pull Request 생성

---

## 📞 지원

이슈가 있으시면 [GitHub Issues](https://github.com/voodoosim/jocopy_bot/issues)에 등록해주세요.

---

## 🎉 변경 이력

### v0.3.0 (2025-11-14)
- ✨ `.소스입력` 독립 명령어 추가
- ✨ `.타겟입력` 독립 명령어 + 권한 검증
- 🎨 채널/그룹 구분 UI 개선 (c/g 접두사)
- 📝 포괄적인 문서화 (1,151줄)

### v0.2.0
- Forum Topics 지원
- 로그 채널 연동
- FSM 기반 UI

### v0.1.0
- 초기 릴리즈
- Manager-Worker 아키텍처
- 기본 미러링 기능

---

**마지막 업데이트**: 2025-11-14  
**Maintainer**: [@voodoosim](https://github.com/voodoosim)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
