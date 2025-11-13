"""워커 관리 핸들러"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import aiosqlite
from config import DATABASE_PATH
from controller import WorkerController

router = Router()

# WorkerController 인스턴스 (전역)
controller = WorkerController()

# 메인 키보드 (항상 보이는 버튼)
def get_main_keyboard():
    """메인 메뉴 키보드"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 메인")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

class MainMenu(StatesGroup):
    """메인 메뉴 FSM"""
    waiting_for_menu_choice = State()

class WorkerRegistration(StatesGroup):
    """워커 등록 FSM"""
    waiting_for_name = State()
    waiting_for_session = State()

class WorkerControl(StatesGroup):
    """워커 제어 FSM"""
    waiting_for_worker_number = State()

class LogChannelSetup(StatesGroup):
    """로그 채널 설정 FSM"""
    waiting_for_channel_id = State()

@router.message(Command("start", "시작"))
@router.message(F.text == "🏠 메인")
async def cmd_start(message: Message, state: FSMContext):
    """시작 명령 & 메인 버튼"""
    await state.clear()  # 모든 상태 초기화
    await message.answer(
        "조카피봇 가동중 !\n\n"
        "①  유닛추가\n"
        "②  유닛목록\n"
        "③  로그설정\n"
        "④  종료\n\n"
        "번호를 입력하세요:",
        reply_markup=get_main_keyboard()
    )
    await state.set_state(MainMenu.waiting_for_menu_choice)

@router.message(MainMenu.waiting_for_menu_choice)
async def process_menu_choice(message: Message, state: FSMContext):
    """메뉴 선택 처리"""
    choice = message.text.strip()

    await state.clear()

    if choice == "1" or choice == "①":
        # 유닛추가
        await message.answer(
            "📝 워커 이름을 입력하세요:\n"
            "예: worker1, my_account 등"
        )
        await state.set_state(WorkerRegistration.waiting_for_name)

    elif choice == "2" or choice == "②":
        # 유닛목록
        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT id, name, status, created_at FROM workers ORDER BY created_at DESC"
            ) as cursor:
                workers = await cursor.fetchall()

        if not workers:
            await message.answer("📭 등록된 유닛이 없습니다.")
            return

        text = "📋 유닛 목록:\n\n"

        for worker_id, name, status, created_at in workers:
            status_emoji = "🟢" if status == "running" else "🔴"
            text += f"{status_emoji} {worker_id}. {name} - {status}\n"

        text += "\n💡 사용법:\n"
        text += "• 시작: 번호 입력 (예: 1)\n"
        text += "• 중지: - 번호 (예: -1)"

        await message.answer(text)
        await state.set_state(WorkerControl.waiting_for_worker_number)

    elif choice == "3" or choice == "③":
        # 로그설정
        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT value FROM config WHERE key = 'log_channel_id'"
            ) as cursor:
                result = await cursor.fetchone()
                current_channel = result[0] if result else "없음"

        await message.answer(
            f"📢 로그 채널 설정\n\n"
            f"현재 로그 채널: {current_channel}\n\n"
            "새 로그 채널 ID를 입력하세요:\n"
            "예: -1001234567890\n\n"
            "💡 채널 ID 확인 방법:\n"
            "1. 채널에 @userinfobot 초대\n"
            "2. 봇이 보내는 메시지에서 채널 ID 확인"
        )
        await state.set_state(LogChannelSetup.waiting_for_channel_id)

    elif choice == "4" or choice == "④":
        # 종료
        await message.answer("⚠️ 봇을 종료하시겠습니까?\n\n정말 종료하려면 '종료확인'을 입력하세요.\n취소하려면 /시작")

    else:
        await message.answer("❌ 잘못된 번호입니다.")

@router.message(WorkerControl.waiting_for_worker_number)
async def process_worker_control(message: Message, state: FSMContext):
    """유닛 시작/중지 처리"""
    try:
        number = int(message.text.strip())
        worker_id = abs(number)

        if number > 0:
            # 시작
            success = await controller.start_worker(worker_id)
            if success:
                await message.answer(f"✅ 유닛 #{worker_id} 시작 중...")
            else:
                await message.answer(f"❌ 유닛 #{worker_id} 시작 실패")
        else:
            # 중지
            success = await controller.stop_worker(worker_id)
            if success:
                await message.answer(f"✅ 유닛 #{worker_id} 중지 완료")
            else:
                await message.answer(f"❌ 유닛 #{worker_id} 중지 실패")

        await state.clear()

    except ValueError:
        await message.answer("❌ 숫자만 입력하세요.\n예: 1 (시작) 또는 -1 (중지)")

@router.message(Command("help", "도움말"))
async def cmd_help(message: Message):
    """도움말"""
    await message.answer(
        "📖 **JoCopy Bot 사용법**\n\n"
        "**워커 관리:**\n"
        "/워커추가 - 워커 추가\n"
        "/워커목록 - 워커 목록\n"
        "/워커시작 <ID> - 워커 시작\n"
        "/워커중지 <ID> - 워커 중지\n"
        "/워커재시작 <ID> - 워커 재시작\n\n"
        "**로그 설정:**\n"
        "/로그채널설정 - 로그 채널 설정\n\n"
        "**상태 확인:**\n"
        "/상태 - 전체 상태\n\n"
        "**워커 명령 (Saved Messages):**\n"
        ".설정 - 소스/타겟 설정\n"
        ".목록 - 채널 목록\n"
        ".미러 - 미러링 시작\n"
        ".카피 - 전체 복사\n"
        ".지정 <ID> - 메시지 ID부터 복사"
    )

@router.message(Command("add_worker", "워커추가", "유닛추가"))
async def cmd_add_worker(message: Message, state: FSMContext):
    """워커 추가 시작"""
    await message.answer(
        "📝 워커 이름을 입력하세요:\n"
        "예: worker1, my_account 등"
    )
    await state.set_state(WorkerRegistration.waiting_for_name)

@router.message(WorkerRegistration.waiting_for_name)
async def process_worker_name(message: Message, state: FSMContext):
    """워커 이름 처리"""
    worker_name = message.text.strip()

    # 이름 검증
    if not worker_name or len(worker_name) < 2:
        await message.answer("❌ 워커 이름은 최소 2자 이상이어야 합니다.")
        return

    # 중복 확인
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT id FROM workers WHERE name = ?", (worker_name,)
        ) as cursor:
            existing = await cursor.fetchone()

    if existing:
        await message.answer(f"❌ 워커 이름 '{worker_name}'은(는) 이미 사용 중입니다.")
        return

    # 상태 저장
    await state.update_data(worker_name=worker_name)
    await message.answer(
        f"✅ 유닛 이름: {worker_name}\n\n"
        "📋 세션 문자열을 입력하세요:\n"
        "(Telegram Session Manager에서 생성)"
    )
    await state.set_state(WorkerRegistration.waiting_for_session)

@router.message(WorkerRegistration.waiting_for_session)
async def process_session_string(message: Message, state: FSMContext):
    """세션 문자열 처리"""
    session_string = message.text.strip()

    # 세션 문자열 기본 검증
    if len(session_string) < 50:
        await message.answer(
            "❌ 유효하지 않은 세션 문자열입니다.\n"
            "세션 문자열은 최소 50자 이상이어야 합니다."
        )
        return

    # 상태 데이터 가져오기
    data = await state.get_data()
    worker_name = data.get("worker_name")

    # DB에 저장
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                INSERT INTO workers (name, session_string, status)
                VALUES (?, ?, 'stopped')
                """,
                (worker_name, session_string)
            )
            await db.commit()

        # 워커 ID 가져오기
        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT id FROM workers WHERE name = ?", (worker_name,)
            ) as cursor:
                worker_id = (await cursor.fetchone())[0]

        await message.answer(
            f"✅ 유닛 '{worker_name}' 등록 완료! (ID: {worker_id})\n\n"
            "다음 단계:\n"
            f"• /유닛시작 {worker_id}\n"
            f"• 유닛 계정의 Saved Messages에서 .설정\n"
            "• /상태"
        )

        # 원본 메시지 삭제 (보안)
        try:
            await message.delete()
        except:
            pass

    except Exception as e:
        await message.answer(f"❌ 등록 실패: {str(e)}")

    finally:
        await state.clear()

@router.message(Command("list_workers", "워커목록", "유닛목록"))
async def cmd_list_workers(message: Message):
    """워커 목록 조회"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT id, name, status, created_at FROM workers ORDER BY created_at DESC"
        ) as cursor:
            workers = await cursor.fetchall()

    if not workers:
        await message.answer("📭 등록된 유닛이 없습니다.\n\n/유닛추가 명령으로 유닛을 추가하세요.")
        return

    text = "📋 유닛 목록:\n\n"
    for worker_id, name, status, created_at in workers:
        status_emoji = "🟢" if status == "running" else "🔴"
        text += f"{status_emoji} #{worker_id} {name} - {status}\n"
        text += f"   등록: {created_at}\n\n"

    await message.answer(text)

@router.message(Command("status", "상태"))
async def cmd_status(message: Message):
    """전체 상태 확인"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # 워커 수
        async with db.execute("SELECT COUNT(*) FROM workers") as cursor:
            worker_count = (await cursor.fetchone())[0]

        # 미러링 수
        async with db.execute(
            "SELECT COUNT(*) FROM mirrors WHERE status = 'active'"
        ) as cursor:
            mirror_count = (await cursor.fetchone())[0]

        # 복사 작업 수
        async with db.execute(
            "SELECT COUNT(*) FROM copies WHERE status IN ('pending', 'running')"
        ) as cursor:
            copy_count = (await cursor.fetchone())[0]

    await message.answer(
        "📊 **JoCopy Bot 상태**\n\n"
        f"👥 워커: {worker_count}개\n"
        f"🔄 미러링: {mirror_count}개\n"
        f"📤 복사 작업: {copy_count}개\n\n"
        "/워커목록 - 워커 상세 정보"
    )

@router.message(Command("start_worker", "워커시작", "유닛시작"))
async def cmd_start_worker(message: Message):
    """워커 시작"""
    try:
        # 워커 ID 파싱
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer(
                "❌ 사용법: /유닛시작 <ID>\n\n"
                "예: /유닛시작 1"
            )
            return

        worker_id = int(args[1])

        # 워커 시작
        success = await controller.start_worker(worker_id)

        if success:
            await message.answer(f"✅ 유닛 #{worker_id} 시작 중...")
        else:
            await message.answer(
                f"❌ 유닛 #{worker_id} 시작 실패\n"
                "이미 실행 중이거나 최대 활성 워커 수 초과"
            )

    except ValueError:
        await message.answer("❌ 잘못된 유닛 ID입니다.")
    except Exception as e:
        await message.answer(f"❌ 오류: {str(e)}")

@router.message(Command("stop_worker", "워커중지", "유닛중지"))
async def cmd_stop_worker(message: Message):
    """워커 중지"""
    try:
        # 워커 ID 파싱
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer(
                "❌ 사용법: /유닛중지 <ID>\n\n"
                "예: /유닛중지 1"
            )
            return

        worker_id = int(args[1])

        # 워커 중지
        success = await controller.stop_worker(worker_id)

        if success:
            await message.answer(f"✅ 유닛 #{worker_id} 중지 완료")
        else:
            await message.answer(f"❌ 유닛 #{worker_id} 중지 실패 (실행 중 아님)")

    except ValueError:
        await message.answer("❌ 잘못된 유닛 ID입니다.")
    except Exception as e:
        await message.answer(f"❌ 오류: {str(e)}")

@router.message(Command("restart_worker", "워커재시작", "유닛재시작"))
async def cmd_restart_worker(message: Message):
    """워커 재시작"""
    try:
        # 워커 ID 파싱
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer(
                "❌ 사용법: /유닛재시작 <ID>\n\n"
                "예: /유닛재시작 1"
            )
            return

        worker_id = int(args[1])

        # 워커 재시작
        await message.answer(f"🔄 유닛 #{worker_id} 재시작 중...")
        success = await controller.restart_worker(worker_id)

        if success:
            await message.answer(f"✅ 유닛 #{worker_id} 재시작 완료")
        else:
            await message.answer(f"❌ 유닛 #{worker_id} 재시작 실패")

    except ValueError:
        await message.answer("❌ 잘못된 유닛 ID입니다.")
    except Exception as e:
        await message.answer(f"❌ 오류: {str(e)}")

@router.message(Command("set_log_channel", "로그채널설정", "로그설정"))
async def cmd_set_log_channel(message: Message, state: FSMContext):
    """로그 채널 설정"""
    # 현재 설정된 로그 채널 확인
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT value FROM config WHERE key = 'log_channel_id'"
        ) as cursor:
            result = await cursor.fetchone()
            current_channel = result[0] if result else "없음"

    await message.answer(
        f"📢 **로그 채널 설정**\n\n"
        f"현재 로그 채널: `{current_channel}`\n\n"
        "새 로그 채널 ID를 입력하세요:\n"
        "예: `-1001234567890`\n\n"
        "💡 채널 ID 확인 방법:\n"
        "1. 채널에 @userinfobot 초대\n"
        "2. 봇이 보내는 메시지에서 채널 ID 확인"
    )
    await state.set_state(LogChannelSetup.waiting_for_channel_id)

@router.message(LogChannelSetup.waiting_for_channel_id)
async def process_log_channel_id(message: Message, state: FSMContext):
    """로그 채널 ID 처리"""
    channel_id = message.text.strip()

    # 채널 ID 검증 (숫자, 옵션으로 -로 시작)
    if not channel_id.lstrip('-').isdigit():
        await message.answer(
            "❌ 잘못된 채널 ID입니다.\n"
            "숫자로 입력하세요. 예: `-1001234567890`"
        )
        return

    # DB에 저장
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # UPSERT (INSERT OR REPLACE)
            await db.execute(
                """
                INSERT OR REPLACE INTO config (key, value, updated_at)
                VALUES ('log_channel_id', ?, CURRENT_TIMESTAMP)
                """,
                (channel_id,)
            )
            await db.commit()

        await message.answer(
            f"✅ **로그 채널 설정 완료!**\n\n"
            f"채널 ID: `{channel_id}`\n\n"
            "이제 모든 워커 로그가 이 채널로 전송됩니다."
        )

    except Exception as e:
        await message.answer(f"❌ 설정 실패: {str(e)}")

    finally:
        await state.clear()

@router.message(Command("shutdown", "종료"))
async def cmd_shutdown(message: Message):
    """봇 종료"""
    await message.answer("⚠️ 봇을 종료하시겠습니까?\n\n정말 종료하려면 /종료확인 을 입력하세요.")

@router.message(Command("shutdown_confirm", "종료확인"))
async def cmd_shutdown_confirm(message: Message):
    """봇 종료 확인"""
    import sys
    await message.answer("👋 조카피봇을 종료합니다...")
    # 모든 워커 종료
    from controller import controller
    for worker_id in list(controller.workers.keys()):
        await controller.stop_worker(worker_id)
    await message.answer("✅ 종료 완료")
    sys.exit(0)
