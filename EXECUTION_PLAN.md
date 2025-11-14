# JoCopy Bot - 실행 계획안

> **작성일**: 2025-11-14
> **목적**: MCP 최적화 + Clean Architecture 적용
> **예상 기간**: 8-12시간 (1-2일)

---

## 📋 목차

1. [현재 상황 요약](#현재-상황-요약)
2. [3가지 실행 옵션](#3가지-실행-옵션)
3. [추천 옵션 상세 계획](#추천-옵션-상세-계획)
4. [리스크 및 대응](#리스크-및-대응)
5. [의사결정 체크리스트](#의사결정-체크리스트)

---

## 📊 현재 상황 요약

### 발견된 문제점

| 문제 | 영향도 | 긴급도 | 설명 |
|------|--------|--------|------|
| **1. Album 핸들러** | 🔴 Critical | 🔴 High | 파일 재업로드로 100배 느림 |
| **2. 핸들러 중복** | 🔴 Critical | 🔴 High | 메모리 누수, 중복 전송 |
| **3. ID 매핑 없음** | 🔴 Critical | 🟡 Medium | 편집/삭제 작동 불가 |
| **4. 배치 미흡** | 🟡 Major | 🟡 Medium | 10배 느림 |
| **5. 코드 비대화** | 🟡 Major | 🟢 Low | worker_bot.py 794줄 |

### 현재 파일 상태

```
✅ 작동 중:
- bot.py (127줄) - Main Bot
- config.py (61줄) - 설정
- database/db.py (98줄) - DB 스키마
- controller/worker_controller.py (284줄) - 프로세스 관리

⚠️ 문제 있음:
- worker/worker_bot.py (794줄) - 5개 치명적 문제
- handlers/worker_handlers.py (484줄) - 비대화

❌ 환경 문제:
- 패키지 미설치 (aiogram, telethon, aiosqlite)
- DB 미초기화
```

---

## 🎯 3가지 실행 옵션

### 옵션 A: 점진적 개선 (안전, 추천)

**개요**: 문제점만 수정하고, 구조는 최소 변경

**장점**:
- ✅ 리스크 낮음
- ✅ 빠른 적용 (4-6시간)
- ✅ 기존 코드 대부분 유지
- ✅ 즉시 성능 개선 체감

**단점**:
- ❌ 코드 구조 여전히 비대함 (794줄)
- ❌ 향후 확장성 제한적

**작업 내용**:
1. Album 핸들러 MCP 적용 (30분)
2. 이벤트 핸들러 중복 제거 (1시간)
3. 메시지 ID 매핑 추가 (1시간)
4. 배치 처리 적용 (1시간)
5. 테스트 및 검증 (1-2시간)

**결과**:
- 성능: 10-100배 향상 ✅
- 안정성: 편집/삭제 작동 ✅
- 코드 품질: 여전히 794줄 (개선 안됨)

---

### 옵션 B: 완전 재설계 (이상적, 시간 소요)

**개요**: Clean Architecture + MCP 최적화 완전 적용

**장점**:
- ✅ 최고의 코드 품질
- ✅ 최고의 확장성
- ✅ 모든 파일 300줄 이하
- ✅ 테스트 용이

**단점**:
- ❌ 높은 리스크
- ❌ 긴 개발 시간 (8-12시간)
- ❌ 대규모 코드 변경
- ❌ 디버깅 시간 추가 가능

**작업 내용**:
1. 환경 설정 (1시간)
2. Services 계층 구현 (2시간)
3. Worker Bot 완전 재작성 (3시간)
4. Handlers 분리 (2시간)
5. 통합 테스트 (2-3시간)

**결과**:
- 성능: 10-100배 향상 ✅
- 안정성: 완벽 ✅
- 코드 품질: 최상 ✅
- 유지보수성: 최상 ✅

---

### 옵션 C: 하이브리드 (균형)

**개요**: 성능 문제는 즉시 수정 + 구조는 단계적 개선

**장점**:
- ✅ 중간 리스크
- ✅ 중간 개발 시간 (6-8시간)
- ✅ 즉시 성능 개선
- ✅ 점진적 구조 개선

**단점**:
- ❌ 2단계 작업 필요
- ❌ 중간 상태 유지 기간 존재

**작업 내용**:

**Phase 1** (4시간): 성능 문제 해결
1. MCP Services만 추가 (2시간)
2. Worker Bot에 적용 (1시간)
3. 테스트 (1시간)

**Phase 2** (3시간): 구조 개선 (나중에)
1. Handlers 분리
2. Clean Architecture 적용

**결과**:
- 성능: Phase 1 완료 시 10-100배 향상 ✅
- 안정성: Phase 1 완료 시 완벽 ✅
- 코드 품질: Phase 2 완료 시 최상 ✅

---

## 📋 추천 옵션 상세 계획

### 🌟 추천: 옵션 C (하이브리드)

**이유**:
1. ✅ 즉시 성능 문제 해결
2. ✅ 낮은 리스크
3. ✅ 단계적 개선 가능
4. ✅ 각 단계별 검증 가능

---

## 🚀 Phase 1: 성능 문제 해결 (4시간)

### Step 1.1: 환경 설정 (30분)

**작업**:
```bash
# 1. 패키지 설치
pip3 install --upgrade pip
pip3 install aiogram==3.13.1
pip3 install telethon==1.41.2
pip3 install aiosqlite
pip3 install python-dotenv

# 2. .env 파일 확인
cat .env

# 3. DB 초기화
python3 -c "import asyncio; from database import init_db; asyncio.run(init_db())"

# 4. 검증
python3 -c "from config import BOT_TOKEN; print('✅ Config OK')"
```

**검증**:
- [ ] 패키지 설치 완료
- [ ] .env 파일 존재
- [ ] DB 생성 확인
- [ ] Config 로딩 성공

---

### Step 1.2: MCP Services 생성 (2시간)

#### 파일 1: `worker/services/__init__.py`
**작업 시간**: 5분
**줄 수**: 10줄

```python
"""Worker Services"""
from .mcp_service import MCPService
from .mapping_service import MappingService

__all__ = ['MCPService', 'MappingService']
```

**검증**:
- [ ] 파일 생성 완료
- [ ] Import 오류 없음

---

#### 파일 2: `worker/services/mcp_service.py`
**작업 시간**: 1시간
**줄 수**: 250줄

```python
"""MCP(Message Copy Protocol) 최적화 서비스"""
import asyncio
import logging
from typing import List, Optional
from telethon import TelegramClient
from telethon.errors import FloodWaitError

logger = logging.getLogger(__name__)

class MCPService:
    """
    Telegram MCP 최적화 서비스

    주요 기능:
    - 배치 메시지 전송 (100개씩)
    - FloodWait 자동 처리
    - Album 최적화 전송
    """

    def __init__(self, client: TelegramClient, batch_size: int = 100):
        self.client = client
        self.batch_size = batch_size

    async def forward_batch(
        self,
        target,
        message_ids: List[int],
        source,
        drop_author: bool = True
    ) -> List[int]:
        """
        배치 메시지 전송 (MCP 활용)

        Args:
            target: 타겟 채팅
            message_ids: 메시지 ID 리스트
            source: 소스 채팅
            drop_author: "Forwarded from" 제거

        Returns:
            전송된 메시지 ID 리스트
        """
        try:
            messages = await self.client.forward_messages(
                target,
                message_ids,
                source,
                drop_author=drop_author
            )

            # 단일 메시지면 리스트로 변환
            if not isinstance(messages, list):
                messages = [messages]

            return [m.id for m in messages if m]

        except FloodWaitError as e:
            logger.warning(f"⏰ FloodWait {e.seconds}초 대기")
            await asyncio.sleep(e.seconds)
            # 재시도
            return await self.forward_batch(target, message_ids, source, drop_author)

    async def forward_all(
        self,
        target,
        source,
        min_id: Optional[int] = None,
        progress_callback=None
    ) -> int:
        """
        전체 메시지 배치 전송

        성능: 1000개 기준
        - 이전: ~10분 (하나씩)
        - 최적화: ~1분 (배치)

        Args:
            target: 타겟 채팅
            source: 소스 채팅
            min_id: 시작 메시지 ID
            progress_callback: 진행률 콜백

        Returns:
            전송된 메시지 수
        """
        batch = []
        count = 0

        async for msg in self.client.iter_messages(source, min_id=min_id, reverse=True):
            batch.append(msg.id)

            # 배치 크기 도달
            if len(batch) >= self.batch_size:
                sent_ids = await self.forward_batch(target, batch, source)
                count += len(sent_ids)

                if progress_callback:
                    await progress_callback(count)

                batch = []
                await asyncio.sleep(1)  # FloodWait 방지

        # 남은 메시지 처리
        if batch:
            sent_ids = await self.forward_batch(target, batch, source)
            count += len(sent_ids)

            if progress_callback:
                await progress_callback(count)

        return count

    async def forward_album(
        self,
        target,
        album_messages: List,
        source
    ) -> List[int]:
        """
        Album (미디어 그룹) MCP 전송

        중요: send_message가 아닌 forward_messages 사용!
        → 100배 빠름 (파일 다운/업 없음)

        Args:
            target: 타겟 채팅
            album_messages: Album 메시지 리스트
            source: 소스 채팅

        Returns:
            전송된 메시지 ID 리스트
        """
        message_ids = [m.id for m in album_messages]
        return await self.forward_batch(target, message_ids, source)
```

**검증**:
- [ ] 파일 생성 완료
- [ ] Syntax 오류 없음
- [ ] Type hints 올바름

---

#### 파일 3: `worker/services/mapping_service.py`
**작업 시간**: 30분
**줄 수**: 120줄

```python
"""메시지 ID 매핑 서비스 (편집/삭제 동기화)"""
import time
import logging
from typing import Dict, Optional, List, Tuple

logger = logging.getLogger(__name__)

class MappingService:
    """
    소스 메시지 ID → 타겟 메시지 ID 매핑

    편집/삭제 동기화에 필수:
    - 소스에서 메시지 123 삭제
    - 타겟에서 매핑된 456 삭제
    """

    def __init__(self, max_size: int = 10000):
        # {source_id: (target_id, timestamp)}
        self.mapping: Dict[int, Tuple[int, float]] = {}
        self.max_size = max_size
        self.hits = 0  # 캐시 히트
        self.misses = 0  # 캐시 미스

    def track(self, source_id: int, target_id: int):
        """
        메시지 매핑 추가

        Args:
            source_id: 소스 메시지 ID
            target_id: 타겟 메시지 ID
        """
        self.mapping[source_id] = (target_id, time.time())

        # 메모리 관리 (오래된 매핑 삭제)
        if len(self.mapping) > self.max_size:
            self._cleanup_old(keep_recent=1000)
            logger.info(f"📊 매핑 정리: {self.max_size} → 1000개")

    def track_batch(self, source_ids: List[int], target_ids: List[int]):
        """
        배치 매핑 추가

        Args:
            source_ids: 소스 메시지 ID 리스트
            target_ids: 타겟 메시지 ID 리스트
        """
        if len(source_ids) != len(target_ids):
            logger.warning(f"⚠️ 매핑 크기 불일치: {len(source_ids)} vs {len(target_ids)}")
            return

        for src_id, tgt_id in zip(source_ids, target_ids):
            self.track(src_id, tgt_id)

    def get_target_id(self, source_id: int) -> Optional[int]:
        """
        타겟 ID 조회

        Args:
            source_id: 소스 메시지 ID

        Returns:
            타겟 메시지 ID (없으면 None)
        """
        result = self.mapping.get(source_id)

        if result:
            self.hits += 1
            return result[0]
        else:
            self.misses += 1
            return None

    def get_target_ids(self, source_ids: List[int]) -> List[int]:
        """
        배치 타겟 ID 조회

        Args:
            source_ids: 소스 메시지 ID 리스트

        Returns:
            타겟 메시지 ID 리스트 (None 제외)
        """
        return [
            tgt_id
            for src_id in source_ids
            if (tgt_id := self.get_target_id(src_id)) is not None
        ]

    def _cleanup_old(self, keep_recent: int):
        """
        오래된 매핑 삭제 (메모리 관리)

        Args:
            keep_recent: 유지할 최근 매핑 수
        """
        # timestamp 기준 정렬
        sorted_items = sorted(
            self.mapping.items(),
            key=lambda x: x[1][1],  # timestamp
            reverse=True
        )

        # 최근 N개만 유지
        self.mapping = dict(sorted_items[:keep_recent])

    def clear(self):
        """모든 매핑 삭제"""
        self.mapping.clear()
        self.hits = 0
        self.misses = 0
        logger.info("🧹 매핑 초기화 완료")

    def get_stats(self) -> dict:
        """통계 조회"""
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0

        return {
            "total_mappings": len(self.mapping),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.1f}%"
        }
```

**검증**:
- [ ] 파일 생성 완료
- [ ] Syntax 오류 없음
- [ ] 메모리 관리 로직 확인

---

### Step 1.3: Worker Bot에 적용 (1시간)

**수정 파일**: `worker/worker_bot.py`

**변경 사항**:

#### 1. Import 추가 (상단)
```python
# 기존 imports...
from .services import MCPService, MappingService
```

#### 2. __init__ 수정
```python
def __init__(self, worker_id: int, worker_name: str, session_string: str):
    # 기존 코드...

    # ✅ 추가: 서비스 초기화
    self.mcp = MCPService(self.client, batch_size=100)
    self.mapping = MappingService(max_size=10000)
    self.mirroring_active = False
```

#### 3. Album 핸들러 수정 (라인 540-547)
```python
# ❌ 이전 코드 삭제
# await self.client.send_message(
#     self.target,
#     file=e.messages,
#     message=[m.message for m in e.messages]
# )

# ✅ 새 코드 추가
@self.client.on(events.Album(chats=self.source))
async def on_album(e):
    if not self.mirroring_active:
        return

    # MCP로 Album 전송
    src_ids = [m.id for m in e.messages]
    sent_ids = await self.mcp.forward_album(
        self.target,
        e.messages,
        self.source
    )

    # 매핑 저장
    self.mapping.track_batch(src_ids, sent_ids)
```

#### 4. 이벤트 핸들러 중복 제거
```python
def _setup_handlers(self):
    # 영구 이벤트 핸들러 (한 번만 등록)

    @self.client.on(events.NewMessage())
    async def on_new(e):
        # 미러링 비활성이거나 다른 채팅이면 무시
        if not self.mirroring_active:
            return
        if e.chat_id != self.source.id:
            return
        if e.message.grouped_id:  # Album은 건너뛰기
            return

        # MCP로 전송
        sent_ids = await self.mcp.forward_batch(
            self.target,
            [e.message.id],
            self.source
        )

        # 매핑 저장
        if sent_ids:
            self.mapping.track(e.message.id, sent_ids[0])

    @self.client.on(events.MessageDeleted())
    async def on_deleted(e):
        if not self.mirroring_active:
            return
        if e.chat_id != self.source.id:
            return

        # 매핑된 타겟 ID 조회
        target_ids = self.mapping.get_target_ids(e.deleted_ids)

        if target_ids:
            await self.client.delete_messages(self.target, target_ids)

    @self.client.on(events.MessageEdited())
    async def on_edited(e):
        if not self.mirroring_active:
            return
        if e.chat_id != self.source.id:
            return

        # 매핑된 타겟 ID 조회
        target_id = self.mapping.get_target_id(e.message.id)

        if target_id and e.message.text:
            await self.client.edit_message(
                self.target,
                target_id,
                e.message.text
            )
```

#### 5. .미러 명령어 수정
```python
@self.client.on(events.NewMessage(pattern=r'^\.미러$', from_users="me"))
async def mirror(event):
    if not self.source or not self.target:
        return await event.reply("❌ .설정 먼저 하세요")

    await event.reply("🔄 미러링 시작...")

    # ✅ MCP로 전체 복사 (배치)
    count = await self.mcp.forward_all(
        self.target,
        self.source,
        progress_callback=lambda c: event.edit(f"📤 복사 중: {c}개")
    )

    # ✅ 미러링 활성화
    self.mirroring_active = True

    await event.reply(f"✅ 초기 복사: {count}개\n🔄 실시간 동기화 활성")
```

#### 6. _copy_all 메소드 수정
```python
async def _copy_all(self, min_id=None, progress_msg=None):
    """✅ MCP Service 사용"""
    return await self.mcp.forward_all(
        self.target,
        self.source,
        min_id=min_id,
        progress_callback=lambda c: progress_msg.edit(f"📤 {c}개") if progress_msg else None
    )
```

**검증**:
- [ ] Syntax 오류 없음
- [ ] Import 오류 없음
- [ ] 기존 기능 유지

---

### Step 1.4: 테스트 (1시간)

#### 테스트 1: 환경 테스트
```bash
# DB 확인
sqlite3 jocopy.db "SELECT name FROM sqlite_master WHERE type='table';"

# Config 확인
python3 -c "from config import *; print('✅ OK')"

# Worker 생성 테스트
python3 -c "
from worker import WorkerBot
print('✅ WorkerBot import OK')
"
```

#### 테스트 2: Main Bot 시작
```bash
# Bot 시작
python3 bot.py > bot.log 2>&1 &

# 로그 확인
tail -f bot.log

# Telegram에서 확인
@JoCopy_bot: /시작
```

#### 테스트 3: Worker 시작
```bash
# Telegram에서
@JoCopy_bot: /유닛시작 1

# Worker Saved Messages에서
.목록
.설정
```

#### 테스트 4: 성능 테스트
```bash
# 100개 메시지 복사 시간 측정
.카피

# Album 전송 테스트
(소스에 사진 여러장 전송)
.미러

# 편집/삭제 테스트
(소스에서 메시지 편집/삭제)
```

**검증 체크리스트**:
- [ ] Main Bot 정상 시작
- [ ] Worker 정상 시작
- [ ] .목록 정상 작동
- [ ] .설정 정상 작동
- [ ] .미러 정상 작동
- [ ] Album 전송 빠름 (1초 이내)
- [ ] 편집 동기화 작동
- [ ] 삭제 동기화 작동
- [ ] 중복 전송 없음

---

## 📊 Phase 1 완료 후 예상 결과

### 성능 개선

| 항목 | 이전 | Phase 1 후 | 개선율 |
|------|------|------------|--------|
| 1000개 메시지 복사 | ~10분 | ~1분 | **10배** |
| 100MB 동영상 Album | ~120초 | ~1초 | **120배** |
| API 호출 수 (1000개) | 1000번 | 10번 | **100배** |
| FloodWait 발생 | 빈번 | 거의 없음 | - |

### 기능 개선

| 기능 | 이전 | Phase 1 후 |
|------|------|------------|
| Album 전송 | ❌ 느림 | ✅ 빠름 |
| 편집 동기화 | ❌ 작동 안함 | ✅ 작동 |
| 삭제 동기화 | ❌ 작동 안함 | ✅ 작동 |
| 중복 전송 | ❌ 발생 | ✅ 없음 |
| 메모리 누수 | ❌ 있음 | ✅ 없음 |

### 코드 상태

```
추가된 파일:
✅ worker/services/__init__.py (10줄)
✅ worker/services/mcp_service.py (250줄)
✅ worker/services/mapping_service.py (120줄)

수정된 파일:
✅ worker/worker_bot.py (794줄 → 800줄)
   - Import 추가
   - 서비스 초기화
   - Album 핸들러 수정
   - 이벤트 핸들러 영구화
   - .미러 명령어 수정
```

---

## 🔄 Phase 2: 구조 개선 (선택, 3시간)

**시점**: Phase 1 완료 후 1-2주 후 (성능 검증 완료 후)

### 작업 내용

1. **Handlers 분리** (1.5시간)
   - `worker/handlers/setup.py` - .설정/.소스입력/.타겟입력
   - `worker/handlers/operations.py` - .미러/.카피/.지정

2. **Manager Handlers 분리** (1시간)
   - `manager/handlers/menu.py`
   - `manager/handlers/worker.py`
   - `manager/handlers/settings.py`

3. **Worker Bot 정리** (30분)
   - 794줄 → 200줄

**결과**:
- 모든 파일 300줄 이하
- Clean Architecture 완성
- 유지보수성 최상

---

## ⚠️ 리스크 및 대응

### 리스크 1: 패키지 설치 실패

**원인**: pip 버전 호환성 문제

**대응**:
```bash
# Plan A: pip 업그레이드
pip3 install --upgrade pip setuptools wheel

# Plan B: 개별 설치
pip3 install aiogram
pip3 install telethon
pip3 install aiosqlite
pip3 install python-dotenv

# Plan C: 가상환경 사용
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

### 리스크 2: Import 오류

**원인**: 모듈 경로 문제

**대응**:
```python
# worker/__init__.py 수정
from .worker_bot import WorkerBot

# worker/services/__init__.py 생성
from .mcp_service import MCPService
from .mapping_service import MappingService
```

---

### 리스크 3: 기존 기능 손상

**원인**: 코드 수정 중 실수

**대응**:
1. Git 커밋 자주 하기
2. 각 단계별 테스트
3. 문제 발생 시 rollback

```bash
# 백업
git add .
git commit -m "backup before changes"

# Rollback
git reset --hard HEAD
```

---

## ✅ 의사결정 체크리스트

### Phase 1 시작 전

- [ ] **시간**: 4시간 투자 가능한가?
- [ ] **환경**: 패키지 설치 권한 있는가?
- [ ] **백업**: 현재 코드 백업했는가?
- [ ] **테스트**: 테스트용 Telegram 계정 있는가?

### Phase 1 중간 체크

- [ ] **Step 1.1**: 환경 설정 완료?
- [ ] **Step 1.2**: Services 생성 완료?
- [ ] **Step 1.3**: Worker Bot 적용 완료?
- [ ] **Step 1.4**: 테스트 통과?

### Phase 1 완료 후

- [ ] **성능**: 10배 빠른가?
- [ ] **안정성**: 편집/삭제 작동하는가?
- [ ] **버그**: 중복 전송 없는가?
- [ ] **만족도**: Phase 2 진행할 가치 있는가?

---

## 🎯 최종 권장사항

### 즉시 시작 (오늘)
✅ **Phase 1: 성능 문제 해결** (4시간)
- 즉시 10-100배 성능 향상
- 낮은 리스크
- 빠른 검증 가능

### 나중에 진행 (1-2주 후)
⏳ **Phase 2: 구조 개선** (3시간)
- 성능 검증 완료 후
- 코드 품질 향상
- 시간 여유 있을 때

---

## 📞 다음 단계

이 계획안을 검토하신 후:

### 선택 1: Phase 1 바로 시작
→ "Phase 1 시작" 이라고 말씀해주세요

### 선택 2: 계획 수정
→ 수정하고 싶은 부분을 알려주세요

### 선택 3: 다른 옵션
→ 원하시는 방향을 말씀해주세요

---

**작성 완료**
어떻게 진행하시겠습니까?
