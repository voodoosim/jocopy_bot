# JoCopy Bot - MCP 최적화 및 재설계 계획서

> **작성일**: 2025-11-14
> **목표**: MCP(Message Copy Protocol) 극대화 + Clean Architecture
> **현재 문제**: 794줄 worker_bot.py, MCP 미활용, 이벤트 핸들러 중복, 메시지 매핑 없음

---

## 📊 현재 코드 문제점 분석

### 🔴 Critical Issues (작동 불가)

#### 1. Album 핸들러 - 파일 재업로드 (성능 100배 차이!)
**위치**: `worker/worker_bot.py:540-547`

```python
# ❌ 현재 코드 (잘못됨!)
@self.client.on(events.Album(chats=self.source))
async def on_album(e):
    await self.client.send_message(
        self.target,
        file=e.messages,                    # ← 파일 다운로드 + 재업로드!
        message=[m.message for m in e.messages]
    )
```

**문제점**:
- Telegram 서버에서 파일 다운로드 → 업로드 (느림!)
- 100MB 파일 = 200MB 트래픽 (다운+업)
- FloodWait 빈번 발생
- 원본 품질 손실 가능

```python
# ✅ 올바른 방법 (MCP 활용!)
@self.client.on(events.Album(chats=self.source))
async def on_album(e):
    await self.client.forward_messages(
        self.target,
        [m.id for m in e.messages],         # ← 메시지 ID만 전달!
        self.source,
        drop_author=True
    )
```

**장점**:
- ✅ 파일 다운로드/업로드 없음 → **100배 빠름**
- ✅ Telegram 서버 내부에서 file_id 복사
- ✅ 원본 품질 유지
- ✅ FloodWait 최소화

---

#### 2. 이벤트 핸들러 중복 등록 (메모리 누수!)
**위치**: `worker/worker_bot.py:465-556`

```python
# ❌ 현재 구조
@self.client.on(events.NewMessage(pattern=r'^\.미러$', from_users="me"))
async def mirror(event):
    # ...

    # ← 여기서 이벤트 핸들러 등록!
    @self.client.on(events.NewMessage(chats=self.source))
    async def on_new(e):
        # ...

    @self.client.on(events.Album(chats=self.source))
    async def on_album(e):
        # ...
```

**문제점**:
- `.미러` 실행할 때마다 핸들러 추가 등록
- `.미러` 2번 → 메시지 2배 전송!
- `.미러` 10번 → 메시지 10배 전송!
- 메모리 누수

```python
# ✅ 올바른 방법
class WorkerBot:
    def __init__(self):
        self.mirroring_active = False
        self.source = None
        self.target = None

    def _setup_handlers(self):
        # 한 번만 등록
        @self.client.on(events.NewMessage())
        async def on_new(e):
            if not self.mirroring_active:
                return
            if e.chat_id != self.source.id:
                return
            # 복사 로직
```

---

#### 3. 메시지 ID 매핑 없음 (편집/삭제 작동 불가)
**위치**: `worker/worker_bot.py:550-555`

```python
# ❌ 현재 코드 (작동 안함!)
@self.client.on(events.MessageDeleted(chats=self.source))
async def on_del(e):
    await self.client.delete_messages(
        self.target,
        e.deleted_ids  # ← 소스의 ID를 타겟에서 삭제 시도!
    )

@self.client.on(events.MessageEdited(chats=self.source))
async def on_edit(e):
    await self.client.edit_message(
        self.target,
        e.message.id,  # ← 소스의 ID를 타겟에서 편집 시도!
        e.message.text
    )
```

**문제점**:
- 소스 메시지 ID: 123
- 타겟 복사된 메시지 ID: 456
- `delete_messages(target, 123)` → 타겟에 123번 메시지 없음!

```python
# ✅ 올바른 방법
class WorkerBot:
    def __init__(self):
        # 메시지 매핑: {source_id: target_id}
        self.message_mapping = {}

    async def forward_and_track(self, source_msg):
        # 전송 후 ID 매핑 저장
        sent = await self.client.forward_messages(...)
        self.message_mapping[source_msg.id] = sent.id

    @self.client.on(events.MessageDeleted(chats=self.source))
    async def on_del(e):
        target_ids = [
            self.message_mapping.get(src_id)
            for src_id in e.deleted_ids
            if src_id in self.message_mapping
        ]
        if target_ids:
            await self.client.delete_messages(self.target, target_ids)
```

---

#### 4. Forum Topics 미완성
**위치**: `worker/worker_bot.py:723-738`

```python
# ❌ 현재 (주석만 있고 작동 안함)
if target_topic_id:
    await self.client.forward_messages(
        self.target, msg.id, self.source,
        drop_author=True
    )
    # Note: forward_messages는 reply_to 파라미터가 없으므로
    # send_message로 재전송 필요
    logger.info(f"토픽 메시지 복사: #{msg.id} → 토픽 #{target_topic_id}")
```

**문제**:
- `forward_messages`는 토픽 지정 불가
- 주석만 있고 실제 구현 없음

```python
# ✅ 올바른 방법
if target_topic_id:
    # MCP 활용 불가 - send_message 사용 필요
    if msg.media:
        await self.client.send_message(
            self.target,
            msg.message,
            file=msg.media,
            reply_to=target_topic_id  # ← 토픽 지정
        )
    else:
        await self.client.send_message(
            self.target,
            msg.message,
            reply_to=target_topic_id
        )
```

**Trade-off**:
- Forum Topics는 MCP 활용 불가 (Telegram API 제한)
- 일반 채널/그룹은 MCP로 최적화
- Forum은 send_message 사용 (느리지만 작동)

---

### 🟡 Performance Issues (느림)

#### 5. 배치 처리 미흡
**위치**: `worker/worker_bot.py:701-778`

```python
# ❌ 현재 (하나씩 API 호출)
async for msg in self.client.iter_messages(self.source):
    await self.client.forward_messages(
        self.target, msg.id, self.source
    )  # ← 메시지마다 API 호출!
    count += 1
```

**문제**:
- 1000개 메시지 = 1000번 API 호출
- 네트워크 레이턴시 누적
- FloodWait 빈번

```python
# ✅ 올바른 방법 (배치)
batch = []
async for msg in self.client.iter_messages(self.source):
    batch.append(msg.id)

    if len(batch) >= 100:  # 100개씩 배치
        await self.client.forward_messages(
            self.target,
            batch,  # ← 한번에 100개!
            self.source,
            drop_author=True
        )
        count += len(batch)
        batch = []
        await asyncio.sleep(1)  # FloodWait 방지

# 남은 메시지 처리
if batch:
    await self.client.forward_messages(...)
```

**성능 개선**:
- 1000개 메시지: 1000번 → 10번 API 호출 (**100배 빠름**)
- 네트워크 레이턴시 최소화
- FloodWait 거의 없음

---

## 🎯 MCP 최적화 완전 재설계

### 새 아키텍처 (Clean + MCP Optimized)

```
jocopy_bot/
├── bot.py (80줄)
│
├── worker/
│   ├── bot.py (200줄) ⭐ 메인
│   │   ├── class WorkerBot
│   │   ├── message_mapping: Dict[int, int]  # 메시지 ID 매핑
│   │   ├── mirroring_active: bool
│   │   └── setup_permanent_handlers()  # 한번만 등록
│   │
│   ├── services/  ⭐ 비즈니스 로직
│   │   ├── mcp_service.py (300줄)
│   │   │   ├── class MCPService
│   │   │   ├── forward_batch()  # 배치 전송
│   │   │   ├── forward_with_tracking()  # ID 매핑
│   │   │   ├── forward_album()  # Album MCP
│   │   │   └── handle_floodwait()
│   │   │
│   │   ├── forum_service.py (150줄)
│   │   │   ├── class ForumService
│   │   │   ├── sync_topics()
│   │   │   └── send_to_topic()  # Forum은 send_message
│   │   │
│   │   └── mapping_service.py (100줄)
│   │       ├── class MappingService
│   │       ├── track_message()
│   │       ├── get_target_id()
│   │       └── cleanup_old()
│   │
│   ├── handlers/ (각 150-200줄)
│   │   ├── setup.py
│   │   └── operations.py
│   │
│   └── events/  ⭐ 이벤트 핸들러 (한번만 등록)
│       └── mirror.py (200줄)
│           ├── on_new_message()
│           ├── on_album()  # MCP 활용!
│           ├── on_deleted()  # 매핑 활용
│           └── on_edited()  # 매핑 활용
```

---

## 🚀 구현 계획

### Phase 1: MCP 서비스 계층 (2시간)

#### 1.1 MCPService 구현
**파일**: `worker/services/mcp_service.py`

```python
"""MCP 최적화 서비스"""
import asyncio
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class MCPService:
    """
    MCP(Message Copy Protocol) 최적화 서비스

    Telegram의 forward_messages를 활용하여
    파일 다운로드/업로드 없이 메시지 복사
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
        배치로 메시지 전송 (MCP 활용)

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
            logger.warning(f"FloodWait {e.seconds}초 대기")
            await asyncio.sleep(e.seconds)
            return await self.forward_batch(target, message_ids, source, drop_author)

    async def forward_all(
        self,
        target,
        source,
        min_id=None,
        progress_callback=None
    ) -> int:
        """
        전체 메시지 배치 전송

        성능: 1000개 메시지 기준
        - 이전: ~10분 (하나씩)
        - 최적화: ~1분 (배치)
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

        return count

    async def forward_album(
        self,
        target,
        album_messages: List,
        source
    ):
        """
        Album (미디어 그룹) MCP 전송

        중요: send_message 대신 forward_messages 사용!
        """
        message_ids = [m.id for m in album_messages]
        return await self.forward_batch(target, message_ids, source)
```

#### 1.2 MappingService 구현
**파일**: `worker/services/mapping_service.py`

```python
"""메시지 ID 매핑 서비스 (편집/삭제 지원)"""
from typing import Dict, Optional, List
import time

class MappingService:
    """
    소스 메시지 ID → 타겟 메시지 ID 매핑

    편집/삭제 동기화에 필수
    """

    def __init__(self, max_size: int = 10000):
        # {source_id: (target_id, timestamp)}
        self.mapping: Dict[int, tuple] = {}
        self.max_size = max_size

    def track(self, source_id: int, target_id: int):
        """메시지 매핑 추가"""
        self.mapping[source_id] = (target_id, time.time())

        # 메모리 관리 (오래된 매핑 삭제)
        if len(self.mapping) > self.max_size:
            self._cleanup_old(1000)

    def track_batch(self, source_ids: List[int], target_ids: List[int]):
        """배치 매핑 추가"""
        for src_id, tgt_id in zip(source_ids, target_ids):
            self.track(src_id, tgt_id)

    def get_target_id(self, source_id: int) -> Optional[int]:
        """타겟 ID 조회"""
        result = self.mapping.get(source_id)
        return result[0] if result else None

    def get_target_ids(self, source_ids: List[int]) -> List[int]:
        """배치 타겟 ID 조회"""
        return [
            self.get_target_id(src_id)
            for src_id in source_ids
            if self.get_target_id(src_id)
        ]

    def _cleanup_old(self, keep_recent: int):
        """오래된 매핑 삭제 (메모리 관리)"""
        # timestamp 기준 정렬
        sorted_items = sorted(
            self.mapping.items(),
            key=lambda x: x[1][1],
            reverse=True
        )

        # 최근 N개만 유지
        self.mapping = dict(sorted_items[:keep_recent])

    def clear(self):
        """모든 매핑 삭제"""
        self.mapping.clear()
```

---

### Phase 2: Worker Bot 리팩토링 (3시간)

#### 2.1 새 WorkerBot 클래스
**파일**: `worker/bot.py`

```python
"""Worker Bot - MCP 최적화 버전"""
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from .services.mcp_service import MCPService
from .services.mapping_service import MappingService
from .services.forum_service import ForumService

class WorkerBot:
    """MCP 최적화 Worker Bot"""

    def __init__(self, worker_id: int, worker_name: str, session_string: str):
        self.worker_id = worker_id
        self.worker_name = worker_name
        self.client = TelegramClient(
            StringSession(session_string),
            API_ID, API_HASH
        )

        # 소스/타겟
        self.source = None
        self.target = None

        # 미러링 상태
        self.mirroring_active = False

        # 서비스
        self.mcp = MCPService(self.client, batch_size=100)
        self.mapping = MappingService(max_size=10000)
        self.forum = ForumService(self.client)

        # 한 번만 핸들러 등록
        self._setup_permanent_handlers()

    def _setup_permanent_handlers(self):
        """
        영구 이벤트 핸들러 (한 번만 등록)

        중요: .미러 명령어와 무관하게 항상 활성
        mirroring_active 플래그로 제어
        """

        # 새 메시지
        @self.client.on(events.NewMessage())
        async def on_new(e):
            # 미러링 비활성 or 다른 채팅
            if not self.mirroring_active:
                return
            if e.chat_id != self.source.id:
                return

            # Album 메시지는 건너뛰기 (on_album에서 처리)
            if e.message.grouped_id:
                return

            # MCP로 전송
            sent_ids = await self.mcp.forward_batch(
                self.target,
                [e.message.id],
                self.source
            )

            # 매핑 저장 (편집/삭제용)
            if sent_ids:
                self.mapping.track(e.message.id, sent_ids[0])

        # Album (미디어 그룹)
        @self.client.on(events.Album())
        async def on_album(e):
            if not self.mirroring_active:
                return
            if e.chat_id != self.source.id:
                return

            # MCP로 Album 전송 (배치)
            src_ids = [m.id for m in e.messages]
            sent_ids = await self.mcp.forward_album(
                self.target,
                e.messages,
                self.source
            )

            # 매핑 저장
            self.mapping.track_batch(src_ids, sent_ids)

        # 메시지 삭제
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

        # 메시지 편집
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

    async def start_mirroring(self):
        """미러링 시작"""
        if not self.source or not self.target:
            raise ValueError("소스/타겟 설정 필요")

        # 전체 복사 (배치)
        count = await self.mcp.forward_all(
            self.target,
            self.source,
            progress_callback=lambda c: print(f"복사중: {c}개")
        )

        # 미러링 활성화
        self.mirroring_active = True

        return count

    async def stop_mirroring(self):
        """미러링 중지"""
        self.mirroring_active = False
        self.mapping.clear()
```

---

### Phase 3: 성능 비교

#### 이전 vs 최적화

| 항목 | 이전 | 최적화 | 개선율 |
|------|------|--------|--------|
| **1000개 메시지 복사** | ~10분 | ~1분 | **10배** |
| **100MB 동영상 Album** | ~120초 | ~1초 | **120배** |
| **API 호출 수** | 1000번 | 10번 | **100배** |
| **FloodWait 발생** | 빈번 | 거의 없음 | - |
| **편집 동기화** | ❌ 작동 안함 | ✅ 작동 | - |
| **삭제 동기화** | ❌ 작동 안함 | ✅ 작동 | - |
| **메모리 누수** | ❌ 있음 | ✅ 없음 | - |

---

## 📋 구현 체크리스트

### Phase 1: MCP Services
- [ ] `worker/services/mcp_service.py` - MCPService 클래스
- [ ] `worker/services/mapping_service.py` - MappingService 클래스
- [ ] `worker/services/forum_service.py` - ForumService 클래스
- [ ] 단위 테스트

### Phase 2: Worker Bot
- [ ] `worker/bot.py` - 새 WorkerBot 클래스
- [ ] 영구 이벤트 핸들러 구현
- [ ] 미러링 시작/중지 로직
- [ ] 메시지 매핑 통합

### Phase 3: Handlers
- [ ] `worker/handlers/setup.py` - .설정/.소스입력/.타겟입력
- [ ] `worker/handlers/operations.py` - .미러/.카피/.지정
- [ ] MCP 서비스 통합

### Phase 4: 테스트
- [ ] 100개 메시지 복사 테스트
- [ ] Album 전송 테스트
- [ ] 편집 동기화 테스트
- [ ] 삭제 동기화 테스트
- [ ] FloodWait 처리 테스트
- [ ] 메모리 누수 테스트

### Phase 5: 문서
- [ ] CLAUDE.md 업데이트
- [ ] README.md 업데이트
- [ ] API 문서 작성

---

## 🎯 예상 결과

### 성능
- ✅ 10-100배 속도 향상
- ✅ FloodWait 최소화
- ✅ 네트워크 트래픽 90% 감소

### 안정성
- ✅ 편집/삭제 동기화 작동
- ✅ 메모리 누수 없음
- ✅ 중복 전송 없음

### 유지보수성
- ✅ 모든 파일 300줄 이하
- ✅ Clean Architecture
- ✅ 테스트 용이

---

**다음 단계**: 이 계획으로 구현을 시작할까요?
