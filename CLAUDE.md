# CLAUDE.md - AI Assistant Guide for JoCopy Bot

> **Project**: JoCopy Bot - Telegram Message Mirroring Bot
> **Version**: v0.3.0
> **Architecture**: Manager-Worker (aiogram + Telethon)
> **Last Updated**: 2025-11-14
> **Language**: Python 3.10+

---

## 📋 Table of Contents

1. [Project Overview](#project-overview)
2. [Codebase Structure](#codebase-structure)
3. [Key Architecture Patterns](#key-architecture-patterns)
4. [Core Components](#core-components)
5. [Database Schema](#database-schema)
6. [Development Workflows](#development-workflows)
7. [Coding Conventions](#coding-conventions)
8. [Common Tasks](#common-tasks)
9. [Testing & Debugging](#testing--debugging)
10. [Important Files Reference](#important-files-reference)

---

## 🎯 Project Overview

### What is JoCopy Bot?

JoCopy Bot is a **Telegram message mirroring and copying system** that enables:
- Real-time message mirroring between channels/groups
- Bulk message copying operations
- Support for Telegram Forum Topics
- Multi-worker account management
- Centralized logging and monitoring

### Core Technologies

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Manager Bot** | aiogram | 3.13.1 | Bot API, FSM, command handling |
| **Worker Bot** | Telethon | 1.41.2 | User client, message forwarding |
| **Database** | SQLite | aiosqlite | Async persistence |
| **Concurrency** | asyncio + multiprocessing | Built-in | Event loops + process isolation |
| **Config** | python-dotenv | Latest | Environment variables |

### Architecture Summary

```
┌─────────────────────────────────┐
│   Manager Bot (aiogram)         │
│   - Single process              │
│   - FSM-based UI                │
│   - Worker orchestration        │
└────────┬────────────────────────┘
         │
         │ spawns (multiprocessing.Process)
         │
    ┌────┴────┬────────┬────────┐
    ▼         ▼        ▼        ▼
┌────────┐ ┌────────┐ ┌────────┐
│Worker 1│ │Worker 2│ │Worker N│  (max 20 concurrent)
│Telethon│ │Telethon│ │Telethon│
└────────┘ └────────┘ └────────┘
    │         │         │
    └─────────┴─────────┘
         │
    ┌────▼────┐
    │ SQLite  │ (Shared state)
    │jocopy.db│
    └─────────┘
```

---

## 📁 Codebase Structure

### Directory Layout

```
jocopy_bot/
├── bot.py                      # Main entry point (Manager Bot)
├── config.py                   # Configuration & environment vars
├── .env.example                # Environment variables template
├── .gitignore                  # Git ignore patterns
│
├── database/                   # Database layer
│   ├── __init__.py            # Exports: init_db, get_db
│   └── db.py                  # SQLite schema & initialization (99 lines)
│
├── controller/                 # Worker process management
│   ├── __init__.py            # Exports: WorkerController
│   └── worker_controller.py   # Process orchestration (285 lines)
│
├── handlers/                   # Manager Bot command handlers
│   ├── __init__.py            # Exports: worker_router
│   └── worker_handlers.py     # FSM-based UI (485 lines)
│
├── worker/                     # Worker Bot implementation
│   ├── __init__.py            # (placeholder)
│   └── worker_bot.py          # Telethon client & commands (795 lines)
│
├── README.md                   # User documentation
├── QUICK_START.md              # Quick start guide
├── DEVELOPMENT_LOG.md          # Detailed development notes
└── CLAUDE.md                   # This file (AI assistant guide)
```

### Line Count Summary

| Module | Lines | Purpose |
|--------|-------|---------|
| bot.py | 128 | Main Bot entry point |
| config.py | 62 | Configuration management |
| database/db.py | 99 | Database schema |
| controller/worker_controller.py | 285 | Process management |
| handlers/worker_handlers.py | 485 | Manager Bot UI |
| worker/worker_bot.py | 795 | Worker Bot core |
| **Total** | **~1,854** | Python code |

---

## 🏗️ Key Architecture Patterns

### 1. Manager-Worker Pattern

**Concept**: Separation of concerns between user interface and worker execution.

- **Manager Bot**: Single aiogram process handling user commands via FSM
- **Worker Bots**: Multiple Telethon processes (1 per account) executing mirroring tasks
- **Communication**: Via shared SQLite database (no shared memory)

**Benefits**:
- Process isolation (worker crashes don't affect Manager)
- Scalable (up to 20 concurrent workers)
- Independent lifecycle management

### 2. Finite State Machine (FSM)

**Used In**: Manager Bot (handlers/worker_handlers.py)

**Purpose**: Multi-step dialogs for worker registration, configuration, etc.

**Example States**:
```python
class WorkerRegistration(StatesGroup):
    waiting_for_name = State()
    waiting_for_session = State()
```

**Flow**:
1. User sends `/유닛추가` → Enter `waiting_for_name`
2. User provides name → Validate → Enter `waiting_for_session`
3. User provides StringSession → Store in DB → Exit FSM

### 3. Event-Driven Architecture

**Used In**: Worker Bot (worker/worker_bot.py)

**Purpose**: Real-time message mirroring via Telethon event handlers

**Key Events**:
```python
@self.client.on(events.NewMessage(chats=self.source))
async def on_new(e):
    # Forward new messages

@self.client.on(events.Album(chats=self.source))
async def on_album(e):
    # Forward media groups

@self.client.on(events.MessageDeleted(chats=self.source))
async def on_del(e):
    # Sync deletions

@self.client.on(events.MessageEdited(chats=self.source))
async def on_edit(e):
    # Sync edits
```

### 4. Conversation API

**Used In**: Worker Bot for interactive setup

**Purpose**: Multi-message dialogs without FSM overhead

**Example**:
```python
me = await self.client.get_me()
async with self.client.conversation(me.id) as conv:
    await conv.send_message("Select source: c1, c2, g1...")
    response = await conv.get_response(timeout=60)
    user_input = response.text.strip()
```

### 5. Process Spawning

**Used In**: WorkerController (controller/worker_controller.py)

**Pattern**:
```python
process = mp.Process(
    target=self._run_worker_process,
    args=(worker_id, worker_name, session_string),
    name=f"Worker-{worker_name}",
    daemon=True
)
process.start()
self.active_workers[worker_id] = process
```

---

## 🔧 Core Components

### Component 1: bot.py (Main Entry Point)

**Purpose**: Manager Bot initialization and execution

**Key Functions**:
- `main()` - Initialize database, create Bot/Dispatcher, start polling
- `poll_logs(bot)` - Background task for centralized log delivery

**Critical Code**:
```python
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(worker_router)  # From handlers/
log_task = asyncio.create_task(poll_logs(bot))
await dp.start_polling(bot)
```

**When to Edit**:
- Adding new routers/handlers
- Changing bot startup behavior
- Modifying log polling logic

---

### Component 2: config.py (Configuration)

**Purpose**: Environment variable loading and validation

**Key Variables**:
```python
BOT_TOKEN           # Main Bot token (from BotFather)
API_ID              # Telegram API ID
API_HASH            # Telegram API Hash
DATABASE_PATH       # SQLite database location
LOG_LEVEL           # Logging level (INFO, DEBUG, etc.)

# Worker limits
MAX_REGISTERED_WORKERS = 100    # Max total workers
MAX_ACTIVE_WORKERS = 20         # Max concurrent running workers
MAX_CONCURRENT_TASKS = 10       # Max operations per worker

# Performance tuning
BATCH_SIZE = 100                # Messages per batch
WORKER_MEMORY_LIMIT_MB = 80     # Per-worker RAM
FLOODWAIT_THRESHOLD_SEC = 60    # FloodWait retry time
```

**When to Edit**:
- Scaling worker limits
- Performance optimization
- Adding new configuration parameters

---

### Component 3: database/db.py (Database Layer)

**Purpose**: SQLite schema definition and initialization

**Key Functions**:
- `init_db()` - Create all tables if not exists
- `get_db()` - Return aiosqlite connection

**Tables** (6 total):
1. **workers** - Worker account management
2. **mirrors** - Real-time mirroring tasks
3. **copies** - Bulk copy operations
4. **logs** - Centralized logging
5. **config** - Global configuration (key-value)
6. **topic_mappings** - Forum Topics mapping

**When to Edit**:
- Adding new tables
- Modifying schemas
- Database migrations

**Important**: Always use `IF NOT EXISTS` for idempotence.

---

### Component 4: controller/worker_controller.py (Process Manager)

**Purpose**: Manage worker process lifecycle

**Class**: `WorkerController`

**Key Methods**:

| Method | Purpose | Database Changes |
|--------|---------|------------------|
| `start_worker(worker_id)` | Spawn new worker process | UPDATE status='starting', process_id=PID |
| `stop_worker(worker_id)` | Terminate worker | UPDATE status='stopped', process_id=NULL |
| `restart_worker(worker_id)` | Stop then start | Multiple updates |
| `get_worker_status(worker_id)` | Check if running | SELECT status |
| `cleanup_dead_workers()` | Detect crashed processes | UPDATE crashed workers |
| `monitor_loop()` | Background monitoring | Periodic cleanup |

**Critical Data**:
```python
self.active_workers: Dict[int, mp.Process]  # worker_id -> Process
self.working_count: int                     # Concurrent task counter
```

**When to Edit**:
- Changing worker startup logic
- Modifying process termination behavior
- Adding monitoring features

---

### Component 5: handlers/worker_handlers.py (Manager Bot UI)

**Purpose**: User-facing command handlers using FSM

**Router**: `worker_router` (aiogram Router)

**FSM State Groups**:

| State Group | States | Purpose |
|------------|--------|---------|
| `MainMenu` | `waiting_for_menu_choice` | Main menu navigation |
| `WorkerRegistration` | `waiting_for_name`, `waiting_for_session` | Worker signup |
| `WorkerControl` | `waiting_for_worker_number` | Worker start/stop |
| `LogChannelSetup` | `waiting_for_channel_id` | Log channel config |

**Commands**:

| Command | Handler | FSM Required |
|---------|---------|--------------|
| `/시작`, `/start` | `cmd_start()` | No |
| `/유닛추가` | `cmd_add_worker()` | Yes (WorkerRegistration) |
| `/유닛목록` | `cmd_list_workers()` | No |
| `/유닛시작 <ID>` | `cmd_start_worker()` | No |
| `/유닛중지 <ID>` | `cmd_stop_worker()` | No |
| `/유닛재시작 <ID>` | `cmd_restart_worker()` | No |
| `/상태` | `cmd_status()` | No |
| `/로그채널설정` | `cmd_set_log_channel()` | Yes (LogChannelSetup) |

**When to Edit**:
- Adding new Manager Bot commands
- Modifying FSM flows
- Changing UI messages (Korean text)

---

### Component 6: worker/worker_bot.py (Worker Bot Core)

**Purpose**: Telethon-based user client for message operations

**Class**: `WorkerBot`

**Initialization**:
```python
def __init__(self, worker_id: int, worker_name: str, session_string: str):
    self.worker_id = worker_id
    self.worker_name = worker_name
    self.client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    self.source = None      # Source chat entity
    self.target = None      # Target chat entity
    self.topic_mapping = {} # Forum topic ID mappings
```

**Worker Commands** (Saved Messages only):

| Command | Pattern | Purpose | Code Location |
|---------|---------|---------|---------------|
| `.목록` | `^\.목록$` | List channels/groups | Line ~250 |
| `.설정` | `^\.설정$` | Unified source+target setup | Line ~280 |
| `.소스입력` | `^\.소스입력$` | Set source only | Line ~350 |
| `.타겟입력` | `^\.타겟입력$` | Set target + permission check | Line ~420 |
| `.미러` | `^\.미러$` | Real-time mirroring | Line ~500 |
| `.카피` | `^\.카피$` | Bulk copy all messages | Line ~580 |
| `.지정 <ID>` | `^\.지정\s+(\d+)$` | Copy from message ID | Line ~650 |

**Key Features**:

1. **Channel/Group Distinction**:
   ```python
   if isinstance(entity, Channel) and entity.broadcast:
       channels.append((entity, title))  # Broadcast channel
   elif isinstance(entity, Chat) or (isinstance(entity, Channel) and not entity.broadcast):
       groups.append((entity, title))    # Group/supergroup
   ```

2. **Input Parsing** (c1, g2 format):
   ```python
   if source_input.startswith('c'):
       num = int(source_input[1:])
       self.source = channels[num - 1][0]
   elif source_input.startswith('g'):
       num = int(source_input[1:])
       self.source = groups[num - 1][0]
   ```

3. **Permission Validation**:
   ```python
   try:
       test_msg = await self.client.send_message(self.target, "🔧 권한 체크...")
       await test_msg.delete()  # Auto-delete test message
   except ChatWriteForbiddenError:
       await event.reply("❌ 타겟 쓰기 권한 없음!\n\n해결 방법:\n...")
   ```

4. **Forward Messages Optimization** (MCP):
   - Uses `forward_messages()` instead of download/re-upload
   - Preserves file IDs and media quality
   - `drop_author=True` removes "Forwarded from..." prefix

5. **Forum Topics Support**:
   - `_is_forum()` - Detect if channel is Forum
   - `_get_forum_topics()` - List all topics
   - `_create_matching_topic()` - Create equivalent in target
   - `_sync_forum_topics()` - Build topic ID mapping

**When to Edit**:
- Adding new worker commands
- Modifying message forwarding logic
- Changing permission check behavior
- Adding new event handlers

---

## 💾 Database Schema

### Table 1: workers

**Purpose**: Worker account management

```sql
CREATE TABLE workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,              -- Worker identifier
    session_string TEXT NOT NULL,           -- Telethon StringSession
    phone TEXT,                             -- Phone number (optional)
    log_channel_id TEXT,                    -- Per-worker log channel
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP,
    status TEXT DEFAULT 'stopped',          -- stopped | starting | running | crashed
    process_id INTEGER                      -- OS process ID
);
```

**Key Operations**:
- `INSERT` on worker registration
- `UPDATE status, process_id` on start/stop
- `SELECT` for worker listing and status checks

---

### Table 2: mirrors

**Purpose**: Real-time mirroring tasks

```sql
CREATE TABLE mirrors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER NOT NULL,
    source_chat TEXT NOT NULL,              -- Source channel/group ID
    target_chat TEXT NOT NULL,              -- Target channel/group ID
    mode TEXT DEFAULT 'mirror',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_message_id INTEGER,                -- Last synced message
    status TEXT DEFAULT 'active',           -- active | paused | stopped
    FOREIGN KEY (worker_id) REFERENCES workers(id)
);
```

---

### Table 3: copies

**Purpose**: Bulk copy operations

```sql
CREATE TABLE copies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER NOT NULL,
    source_chat TEXT NOT NULL,
    target_chat TEXT NOT NULL,
    mode TEXT DEFAULT 'copy',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_messages INTEGER,                 -- Expected count
    copied_messages INTEGER DEFAULT 0,      -- Progress
    last_message_id INTEGER,
    status TEXT DEFAULT 'pending',          -- pending | running | completed | failed
    FOREIGN KEY (worker_id) REFERENCES workers(id)
);
```

---

### Table 4: logs

**Purpose**: Centralized logging with delivery tracking

```sql
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER NOT NULL,
    worker_name TEXT NOT NULL,
    level TEXT NOT NULL,                    -- INFO | WARNING | ERROR | SUCCESS | START | STOP
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent BOOLEAN DEFAULT 0,                 -- Delivery flag
    FOREIGN KEY (worker_id) REFERENCES workers(id)
);
```

**Log Levels**:
- `INFO` - General information
- `WARNING` - Non-critical issues
- `ERROR` - Critical errors
- `SUCCESS` - Successful operations
- `START` - Worker started
- `STOP` - Worker stopped

---

### Table 5: config

**Purpose**: Global key-value configuration

```sql
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Example Keys**:
- `log_channel_id` - Global log channel
- `max_workers` - Dynamic worker limit
- `maintenance_mode` - System maintenance flag

---

### Table 6: topic_mappings

**Purpose**: Forum Topics mapping for synchronized copying

```sql
CREATE TABLE topic_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER NOT NULL,
    source_chat_id TEXT NOT NULL,
    target_chat_id TEXT NOT NULL,
    source_topic_id INTEGER NOT NULL,       -- Source Forum topic ID
    target_topic_id INTEGER NOT NULL,       -- Target Forum topic ID
    topic_title TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (worker_id) REFERENCES workers(id),
    UNIQUE(worker_id, source_chat_id, source_topic_id)
);
```

**Purpose**: Map source Forum topics to target Forum topics for accurate message forwarding.

---

## 🔄 Development Workflows

### Workflow 1: Adding a New Manager Bot Command

**Steps**:

1. **Define Command Handler** (handlers/worker_handlers.py):
   ```python
   @router.message(Command("새명령어"))
   async def cmd_new_command(message: Message):
       await message.answer("새 명령어 실행!")
   ```

2. **Add FSM State** (if multi-step):
   ```python
   class NewCommandStates(StatesGroup):
       waiting_for_input = State()
   ```

3. **Update Help Text** (in `cmd_help()` handler)

4. **Test**:
   ```bash
   # Restart Manager Bot
   ps aux | grep "python3 bot.py" | awk '{print $2}' | xargs kill -9
   python3 bot.py > bot.log 2>&1 &

   # Test command in Telegram
   @JoCopy_bot: /새명령어
   ```

---

### Workflow 2: Adding a New Worker Bot Command

**Steps**:

1. **Define Event Handler** (worker/worker_bot.py in `_setup_handlers()`):
   ```python
   @self.client.on(events.NewMessage(pattern=r'^\.새명령$', from_users="me"))
   async def new_command(event):
       await event.reply("새 Worker 명령어!")
   ```

2. **Add Business Logic**:
   ```python
   async def new_command(event):
       # Access worker data
       worker_id = self.worker_id

       # Database operations
       async with aiosqlite.connect(DATABASE_PATH) as db:
           await db.execute("INSERT INTO ...")
           await db.commit()

       # Logging
       await self.log("New command executed", "INFO")

       await event.reply("✅ 완료!")
   ```

3. **Test**:
   ```bash
   # Stop worker
   @JoCopy_bot: /유닛중지 1

   # Clear Python cache
   find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

   # Reset DB status
   python3 -c "import asyncio, aiosqlite; asyncio.run((lambda: aiosqlite.connect('./jocopy.db'))()).execute('UPDATE workers SET status=\"stopped\", process_id=NULL').commit()"

   # Start worker
   @JoCopy_bot: /유닛시작 1

   # Test command
   Worker Saved Messages: .새명령
   ```

---

### Workflow 3: Modifying Database Schema

**Steps**:

1. **Update Schema** (database/db.py in `init_db()`):
   ```python
   await db.execute("""
       CREATE TABLE IF NOT EXISTS new_table (
           id INTEGER PRIMARY KEY,
           field TEXT NOT NULL
       )
   """)
   ```

2. **Add Migration** (if table exists):
   ```python
   # Check if column exists
   cursor = await db.execute("PRAGMA table_info(workers)")
   columns = [row[1] for row in await cursor.fetchall()]

   if 'new_field' not in columns:
       await db.execute("ALTER TABLE workers ADD COLUMN new_field TEXT")
   ```

3. **Update Access Code** (wherever table is used)

4. **Test**:
   ```bash
   # Backup database
   cp jocopy.db jocopy.db.backup

   # Restart bot (will run init_db())
   ps aux | grep "python3 bot.py" | awk '{print $2}' | xargs kill -9
   python3 bot.py > bot.log 2>&1 &

   # Verify schema
   sqlite3 jocopy.db ".schema new_table"
   ```

---

### Workflow 4: Debugging Worker Issues

**Common Issues**:

1. **Worker won't start**:
   ```bash
   # Check DB status
   sqlite3 jocopy.db "SELECT id, name, status, process_id FROM workers;"

   # Reset stuck workers
   python3 -c "
   import asyncio
   import aiosqlite
   async def reset():
       async with aiosqlite.connect('./jocopy.db') as db:
           await db.execute('UPDATE workers SET status=\"stopped\", process_id=NULL')
           await db.commit()
   asyncio.run(reset())
   "

   # Retry start
   @JoCopy_bot: /유닛시작 1
   ```

2. **Commands not responding**:
   ```bash
   # Check if process is alive
   ps aux | grep "Worker-"

   # Check logs
   sqlite3 jocopy.db "SELECT * FROM logs WHERE worker_id=1 ORDER BY created_at DESC LIMIT 10;"

   # Restart worker
   @JoCopy_bot: /유닛재시작 1
   ```

3. **Permission errors**:
   ```
   .타겟입력 → "❌ 타겟 쓰기 권한 없음!"

   Fix:
   1. Go to target channel/group
   2. Add worker account as admin
   3. Enable "Post Messages" permission
   4. Retry: .타겟입력
   ```

---

## 📐 Coding Conventions

### 1. Naming Conventions

**Variables**:
- `snake_case` for all variables, functions, methods
- `UPPER_CASE` for constants (config.py)

**Classes**:
- `PascalCase` for class names
- Example: `WorkerBot`, `WorkerController`

**Database**:
- `snake_case` for table names and columns
- Plural for table names: `workers`, `mirrors`, `logs`

**Files**:
- `snake_case.py` for Python modules
- `UPPERCASE.md` for documentation

---

### 2. Code Organization

**Import Order**:
1. Standard library (asyncio, os, etc.)
2. Third-party (aiogram, telethon, aiosqlite)
3. Local modules (config, database, etc.)

**Example**:
```python
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher
from telethon import TelegramClient

from config import BOT_TOKEN
from database import init_db
```

---

### 3. Async Patterns

**Always use `async/await`**:
```python
# Good
async def fetch_data():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT * FROM workers")
        return await cursor.fetchall()

# Bad (blocking)
def fetch_data():
    conn = sqlite3.connect(DATABASE_PATH)
    return conn.execute("SELECT * FROM workers").fetchall()
```

**Use `asyncio.create_task()` for background tasks**:
```python
# In bot.py
log_task = asyncio.create_task(poll_logs(bot))
```

---

### 4. Error Handling

**Always catch specific exceptions**:
```python
# Good
try:
    await self.client.send_message(chat, text)
except ChatWriteForbiddenError:
    await self.log("No write permission", "ERROR")
except FloodWaitError as e:
    await asyncio.sleep(e.seconds)
    await self.client.send_message(chat, text)  # Retry

# Bad (too broad)
try:
    await self.client.send_message(chat, text)
except Exception as e:
    print(f"Error: {e}")
```

**Common Telethon Exceptions**:
- `ChatWriteForbiddenError` - No permission to write
- `FloodWaitError` - Rate limited (has `.seconds` attribute)
- `MessageIdInvalidError` - Message deleted or not found
- `ChannelPrivateError` - Channel is private
- `UserBannedInChannelError` - User banned

---

### 5. Database Patterns

**Use context managers**:
```python
async with aiosqlite.connect(DATABASE_PATH) as db:
    await db.execute("INSERT INTO logs ...")
    await db.commit()
```

**Parameterized queries** (prevent SQL injection):
```python
# Good
await db.execute("SELECT * FROM workers WHERE id = ?", (worker_id,))

# Bad (SQL injection risk)
await db.execute(f"SELECT * FROM workers WHERE id = {worker_id}")
```

---

### 6. Logging

**Use structured logging**:
```python
# In Worker Bot
await self.log("Mirror started", "START")
await self.log(f"Copied {count} messages", "SUCCESS")
await self.log("Permission denied", "ERROR")

# In Manager Bot
logging.info(f"Worker {worker_id} started")
logging.error(f"Failed to start worker: {e}")
```

**Log Levels**:
- `INFO` - Regular operations
- `SUCCESS` - Successful completions
- `WARNING` - Non-critical issues
- `ERROR` - Critical failures
- `START` - Worker lifecycle (start)
- `STOP` - Worker lifecycle (stop)

---

## 🛠️ Common Tasks

### Task 1: Add a New Configuration Parameter

**File**: config.py

```python
# Add to config.py
NEW_PARAMETER = int(os.getenv("NEW_PARAMETER", "10"))

# Add to .env.example
NEW_PARAMETER=10

# Use in code
from config import NEW_PARAMETER

if count > NEW_PARAMETER:
    # ...
```

---

### Task 2: Add a New Database Table

**File**: database/db.py

```python
# In init_db() function
await db.execute("""
    CREATE TABLE IF NOT EXISTS new_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_id INTEGER NOT NULL,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (worker_id) REFERENCES workers(id)
    )
""")
await db.commit()
```

---

### Task 3: Add Input Validation

**Pattern**:
```python
# In handlers or worker commands
user_input = message.text.strip()

# Length validation
if len(user_input) < 2:
    await message.answer("❌ 최소 2자 이상 입력하세요")
    return

# Format validation
if not user_input.startswith('c') and not user_input.startswith('g'):
    await message.answer("❌ c1, c2, g1, g2 형식으로 입력하세요")
    return

# Range validation
try:
    num = int(user_input[1:])
    if num < 1 or num > len(items):
        await message.answer(f"❌ 1~{len(items)} 범위 내에서 입력하세요")
        return
except ValueError:
    await message.answer("❌ 숫자를 입력하세요")
    return
```

---

### Task 4: Handle FloodWait Errors

**Pattern**:
```python
from telethon.errors import FloodWaitError
import asyncio

try:
    await self.client.forward_messages(target, msg_id, source)
except FloodWaitError as e:
    await self.log(f"FloodWait {e.seconds}초 대기", "WARNING")
    await asyncio.sleep(e.seconds)
    await self.client.forward_messages(target, msg_id, source)  # Retry
```

---

### Task 5: Add Progress Reporting

**Pattern**:
```python
total = 1000
for i in range(total):
    # Process item

    # Report every 50 items
    if (i + 1) % 50 == 0:
        progress = (i + 1) / total * 100
        await event.edit(f"⏳ 진행중: {i+1}/{total} ({progress:.1f}%)")
```

---

## 🧪 Testing & Debugging

### Testing Checklist

**Before Committing Code**:
- [ ] Clear Python cache: `find . -type d -name "__pycache__" -exec rm -rf {} +`
- [ ] Restart Manager Bot
- [ ] Reset worker status in DB
- [ ] Test Manager Bot commands (`/유닛목록`, `/유닛시작 1`)
- [ ] Test Worker Bot commands (`.목록`, `.설정`, `.미러`)
- [ ] Check logs: `sqlite3 jocopy.db "SELECT * FROM logs ORDER BY created_at DESC LIMIT 20;"`
- [ ] Verify no errors in `bot.log`

---

### Debug Commands

**Check Running Processes**:
```bash
ps aux | grep "python3 bot.py"
ps aux | grep "Worker-"
```

**Database Queries**:
```bash
# Worker status
sqlite3 jocopy.db "SELECT id, name, status, process_id FROM workers;"

# Recent logs
sqlite3 jocopy.db "SELECT worker_name, level, message, created_at FROM logs ORDER BY created_at DESC LIMIT 20;"

# Active mirrors
sqlite3 jocopy.db "SELECT * FROM mirrors WHERE status='active';"
```

**Reset Everything**:
```bash
# Kill all processes
ps aux | grep "python3" | grep -v grep | awk '{print $2}' | xargs -r kill -9

# Clear cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

# Reset DB
python3 -c "
import asyncio
import aiosqlite
async def reset():
    async with aiosqlite.connect('./jocopy.db') as db:
        await db.execute('UPDATE workers SET status=\"stopped\", process_id=NULL')
        await db.commit()
asyncio.run(reset())
"

# Restart bot
python3 bot.py > bot.log 2>&1 &
sleep 3
tail -20 bot.log
```

---

### Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `Worker won't start` | DB status stuck | Reset DB: `UPDATE workers SET status='stopped'` |
| `Commands not responding` | Worker process dead | Restart: `/유닛재시작 1` |
| `❌ 타겟 쓰기 권한 없음!` | No admin permission | Add worker as admin with "Post Messages" |
| `FloodWaitError` | Telegram rate limit | Auto-handled (waits and retries) |
| `MessageIdInvalidError` | Message deleted | Skip and continue |
| `Cannot find channel` | Wrong ID or not joined | Join channel first |

---

## 📚 Important Files Reference

### Configuration Files

| File | Purpose | Git Tracked |
|------|---------|-------------|
| `.env` | Environment variables (secrets) | ❌ No |
| `.env.example` | Template for `.env` | ✅ Yes |
| `config.py` | Configuration loader | ✅ Yes |
| `.gitignore` | Git ignore patterns | ✅ Yes |

### Documentation Files

| File | Purpose | Audience |
|------|---------|----------|
| `README.md` | User documentation | Users |
| `QUICK_START.md` | Quick start guide | Users |
| `DEVELOPMENT_LOG.md` | Development notes | Developers |
| `CLAUDE.md` | AI assistant guide | AI Assistants |

### Core Code Files

| File | Purpose | Lines |
|------|---------|-------|
| `bot.py` | Main Bot entry | 128 |
| `config.py` | Configuration | 62 |
| `database/db.py` | Database schema | 99 |
| `controller/worker_controller.py` | Process management | 285 |
| `handlers/worker_handlers.py` | Manager Bot UI | 485 |
| `worker/worker_bot.py` | Worker Bot core | 795 |

---

## 🎯 Key Takeaways for AI Assistants

### When Working on This Codebase:

1. **Understand the Architecture**: Manager-Worker pattern with process isolation
2. **Database is Shared State**: All IPC happens via SQLite
3. **Always Clear Cache**: Python `__pycache__` can cause stale code issues
4. **Test in Telegram**: Most functionality requires real Telegram interaction
5. **Check Logs**: Use SQLite `logs` table for debugging
6. **Reset Workers**: Use DB reset command when workers get stuck
7. **Korean Language**: UI messages are in Korean (Korean documentation)
8. **Forum Topics**: Special handling for Telegram Forum channels
9. **FloodWait**: Automatic retry logic for rate limits
10. **Permissions**: Target channels require admin with "Post Messages"

### Before Making Changes:

- Read relevant documentation (README.md, DEVELOPMENT_LOG.md)
- Understand which component you're modifying (Manager vs Worker)
- Check database schema if adding/modifying data
- Consider impact on running workers (process restart needed?)
- Test both Manager Bot and Worker Bot after changes

### After Making Changes:

- Clear Python cache
- Restart Manager Bot
- Reset worker status in DB
- Test commands in Telegram
- Check `bot.log` for errors
- Verify logs in database

---

## 📞 Support & Resources

**Documentation**:
- [README.md](README.md) - Full user documentation
- [QUICK_START.md](QUICK_START.md) - Quick start guide
- [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) - Development notes

**Key Technologies**:
- [aiogram Documentation](https://docs.aiogram.dev/)
- [Telethon Documentation](https://docs.telethon.dev/)
- [Python asyncio](https://docs.python.org/3/library/asyncio.html)

**Git**:
- Repository: https://github.com/voodoosim/jocopy_bot
- Branch: `claude/claude-md-mhydk2tnd9yl056u-01G69vKSCqiqkjVowUR7qzsc`

---

**Last Updated**: 2025-11-14
**Version**: v0.3.0
**Maintainer**: @voodoosim
**Created by**: Claude Code
