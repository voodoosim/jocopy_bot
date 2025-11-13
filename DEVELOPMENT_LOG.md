# JoCopy Bot - Development Log

> **Version**: v0.3.0  
> **Last Updated**: 2025-11-14  
> **Status**: Production Ready

## 프로젝트 개요

**JoCopy Bot**은 Telegram 메시지 미러링 및 복사를 위한 Manager-Worker 아키텍처 기반 봇입니다.

### 핵심 특징

- **Manager-Worker 구조**: aiogram (Manager) + Telethon (Worker)
- **독립적 소스/타겟 설정**: `.소스입력`, `.타겟입력` 명령어
- **권한 자동 검증**: 타겟 채널 쓰기 권한 체크
- **MCP 최적화**: forward_messages 기반 고성능 복사
- **Forum Topics 지원**: 토픽 구조 완전 복사
- **실시간 미러링**: 이벤트 기반 동기화

---

## v0.3.0 변경 사항 (2025-11-14)

### 신규 기능

#### 1. `.소스입력` 명령어
- **위치**: `worker/worker_bot.py:250-344`
- **기능**: 소스 채널/그룹 독립 설정
- **UI**: conversation API 기반 대화형
- **입력 형식**: c1 (채널), g1 (그룹)

#### 2. `.타겟입력` 명령어
- **위치**: `worker/worker_bot.py:346-462`
- **기능**: 타겟 채널/그룹 독립 설정 + 권한 검증
- **UI**: conversation API 기반 대화형
- **권한 체크**: 자동 쓰기 권한 확인
- **에러 처리**: 상세 해결 방법 제공

### 개선 사항

- 채널/그룹 명확한 구분 표시 (⁘ 구분선)
- c/g 접두사 입력 방식 (직관적)
- 입력 검증 강화 (범위 체크, ValueError 처리)
- 명확한 안내 메시지 (다음 단계 가이드)

---

## 현재 기능

### Manager Bot 명령어 (@JoCopy_bot)

| 명령어 | 설명 |
|--------|------|
| `/유닛목록` | 등록된 워커 목록 |
| `/유닛추가` | 새 워커 등록 |
| `/유닛시작 [ID]` | 워커 시작 |
| `/유닛중지 [ID]` | 워커 중지 |
| `/유닛재시작 [ID]` | 워커 재시작 |
| `/로그설정` | 로그 채널 설정 |
| `/상태` | 전체 상태 확인 |

### Worker 명령어 (Saved Messages)

| 명령어 | 설명 | 버전 |
|--------|------|------|
| `.소스입력` | 소스만 설정 | v0.3.0 |
| `.타겟입력` | 타겟만 설정 + 권한 체크 | v0.3.0 |
| `.설정` | 소스+타겟 한번에 설정 | v0.1.0 |
| `.목록` | 채널/그룹 목록 | v0.1.0 |
| `.미러` | 실시간 미러링 시작 | v0.1.0 |
| `.카피` | 전체 메시지 복사 | v0.1.0 |
| `.지정 [ID]` | 메시지 ID부터 복사 | v0.1.0 |

---

## 아키텍처

### 디렉토리 구조

```
jocopy_bot/
├── bot.py                    # Main Bot (aiogram)
├── config.py                 # 설정
├── jocopy.db                 # SQLite DB
├── worker/
│   ├── __init__.py
│   └── worker_bot.py         # Worker Bot (Telethon)
├── controller/
│   ├── __init__.py
│   └── worker_controller.py  # 프로세스 관리
├── handlers/
│   ├── __init__.py
│   └── worker_handlers.py    # Manager Bot 핸들러
├── database/
│   ├── __init__.py
│   └── db.py                 # DB 초기화
├── README.md
├── QUICK_START.md
└── DEVELOPMENT_LOG.md        # 이 문서
```

### 데이터베이스 스키마

#### workers 테이블
```sql
CREATE TABLE workers (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    session_string TEXT NOT NULL,
    status TEXT DEFAULT 'stopped',
    process_id INTEGER,
    created_at TIMESTAMP
);
```

#### topic_mappings 테이블 (Forum 지원)
```sql
CREATE TABLE topic_mappings (
    id INTEGER PRIMARY KEY,
    worker_id INTEGER NOT NULL,
    source_chat_id TEXT NOT NULL,
    target_chat_id TEXT NOT NULL,
    source_topic_id INTEGER NOT NULL,
    target_topic_id INTEGER NOT NULL,
    topic_title TEXT NOT NULL,
    created_at TIMESTAMP,
    UNIQUE(worker_id, source_chat_id, source_topic_id)
);
```

### 프로세스 구조

```
Main Bot (aiogram)
├── WorkerController
│   ├── Worker Process 1 (Telethon)
│   ├── Worker Process 2 (Telethon)
│   └── Worker Process N (Telethon)
├── Handlers Router
└── Database Manager
```

---

## 테스트 가이드

### 시나리오 1: 첫 설정 (소스+타겟)

```
1. @JoCopy_bot에서: /유닛시작 1
2. 워커 Saved Messages:
   .소스입력 → c1
   .타겟입력 → g2
   .미러
```

### 시나리오 2: 타겟만 변경

```
1. 이미 소스가 설정되어 있음
2. .타겟입력 → c3 (새 타겟)
3. .미러
```

### 시나리오 3: 여러 타겟에 순차 복사

```
1. .소스입력 → c1
2. .타겟입력 → g1 → .카피 (완료 대기)
3. .타겟입력 → g2 → .카피 (완료 대기)
4. .타겟입력 → g3 → .카피
```

---

## 문제 해결

### 1. 워커가 시작 안됨

**증상**: `/유닛시작 1` 후 응답 없음

**해결**:
```bash
# DB 상태 리셋
python3 -c "
import asyncio
import aiosqlite
async def reset():
    async with aiosqlite.connect('./jocopy.db') as db:
        await db.execute('UPDATE workers SET status = \"stopped\", process_id = NULL')
        await db.commit()
asyncio.run(reset())
"

# 워커 재시작
@JoCopy_bot에서: /유닛시작 1
```

### 2. 명령어가 응답 안함

**원인**: 워커 프로세스가 죽음

**해결**: `@JoCopy_bot`에서 `/유닛시작 1`

### 3. 권한 오류

**증상**:
```
.타겟입력
→ "❌ 타겟 쓰기 권한 없음!"
```

**해결**:
1. 타겟 채널/그룹으로 이동
2. 워커 계정을 관리자로 추가
3. "메시지 게시" 권한 활성화
4. `.타겟입력` 다시 실행

### 4. 캐시 문제

**증상**: 코드 수정했는데 반영 안됨

**해결**:
```bash
# 모든 봇/워커 종료
ps aux | grep "python3" | grep -v grep | awk '{print $2}' | xargs -r kill -9

# 캐시 제거
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

# DB 리셋
python3 -c "
import asyncio
import aiosqlite
async def reset():
    async with aiosqlite.connect('./jocopy.db') as db:
        await db.execute('UPDATE workers SET status = \"stopped\", process_id = NULL')
        await db.commit()
asyncio.run(reset())
"

# 봇 재시작
python3 bot.py > bot.log 2>&1 &
sleep 3
tail -20 bot.log
```

### 5. Forum Topics 복사 안됨

**원인**: 소스가 Forum이 아님

**확인**:
```python
async def check_forum(chat_id):
    entity = await client.get_entity(chat_id)
    print(f"Forum: {getattr(entity, 'forum', False)}")
```

---

## 코드 참조

### conversation API 사용

**위치**: `worker/worker_bot.py:273-298`

```python
me = await self.client.get_me()
async with self.client.conversation(me.id) as conv:
    await conv.send_message("목록 표시...")
    resp = await conv.get_response(timeout=60)
    user_input = resp.text.strip()
```

### 채널/그룹 구분

**위치**: `worker/worker_bot.py:258-269`

```python
if isinstance(entity, Channel) and entity.broadcast:
    channels.append((entity, title))  # 채널
elif isinstance(entity, Chat) or (isinstance(entity, Channel) and not entity.broadcast):
    groups.append((entity, title))  # 그룹
```

### 입력 파싱 (c1, g2)

**위치**: `worker/worker_bot.py:306-334`

```python
if source_input.startswith('c'):
    num = int(source_input[1:])
    if num < 1 or num > len(channels):
        return  # 에러
    self.source = channels[num - 1][0]
elif source_input.startswith('g'):
    num = int(source_input[1:])
    if num < 1 or num > len(groups):
        return  # 에러
    self.source = groups[num - 1][0]
```

---

## 버전 히스토리

### v0.3.0 (2025-11-14)
- ✅ `.소스입력` 명령어 추가
- ✅ `.타겟입력` 명령어 추가
- ✅ 권한 체크 로직 구현
- ✅ 채널/그룹 구분 UI 개선
- ✅ 포괄적인 문서화

### v0.2.0 (2025-11-13)
- ✅ `.설정` 명령어 개선
- ✅ 채널/그룹 구분 표시
- ✅ c/g 접두사 입력 방식

### v0.1.0 (2025-11-12)
- ✅ Manager-Worker 아키텍처
- ✅ 기본 명령어 구현
- ✅ forward_messages 최적화
- ✅ Forum Topics 지원

---

**작성자**: Claude Code  
**GitHub**: https://github.com/voodoosim/jocopy_bot
