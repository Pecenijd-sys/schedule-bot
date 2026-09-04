import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, DAY_MAP
from data import get_schedule_for_group, format_schedule
from keyboards import groups_keyboard, main_menu_keyboard, days_keyboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Простое хранилище выбранных групп (user_id -> group)
user_groups: dict[int, str] = {}


class Form(StatesGroup):
    waiting_for_group = State()


async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # ========== /start ==========
    @dp.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext):
        user_id = message.from_user.id
        if user_id in user_groups:
            group = user_groups[user_id]
            await message.answer(
                f"Привіт! 👋\nТвоя група: <b>{group}</b>\n\n"
                "Обери, що хочеш подивитись:",
                reply_markup=main_menu_keyboard()
            )
        else:
            await message.answer(
                "Привіт! 👋\nЯ бот з розкладом пар для 1 курсу ІПЗ.\n\n"
                "Спочатку обери свою групу:",
                reply_markup=groups_keyboard()
            )
            await state.set_state(Form.waiting_for_group)

    # ========== Выбор группы ==========
    @dp.callback_query(F.data.startswith("group:"))
    async def process_group(callback: CallbackQuery, state: FSMContext):
        group = callback.data.split(":")[1]
        user_groups[callback.from_user.id] = group
        await state.clear()

        await callback.message.edit_text(
            f"✅ Групу <b>{group}</b> збережено!\n\n"
            "Тепер можеш користуватись меню нижче 👇"
        )
        await callback.message.answer(
            "Обери дію:",
            reply_markup=main_menu_keyboard()
        )
        await callback.answer()

    # ========== Сьогодні ==========
    @dp.message(F.text == "📅 Сьогодні")
    async def today_schedule(message: Message):
        user_id = message.from_user.id
        if user_id not in user_groups:
            await message.answer("Спочатку обери групу:", reply_markup=groups_keyboard())
            return

        group = user_groups[user_id]
        today = datetime.now()
        day_name = DAY_MAP[today.weekday()]

        if day_name in ["Субота", "Неділя"]:
            await message.answer(f"📅 <b>Сьогодні ({day_name})</b>\n\nВихідний! Пар немає 🎉")
            return

        df = get_schedule_for_group(group, day_name)
        text = format_schedule(df, title=f"📅 Сьогодні — {day_name} ({group})")
        await message.answer(text, disable_web_page_preview=True)

    # ========== Завтра ==========
    @dp.message(F.text == "➡️ Завтра")
    async def tomorrow_schedule(message: Message):
        user_id = message.from_user.id
        if user_id not in user_groups:
            await message.answer("Спочатку обери групу:", reply_markup=groups_keyboard())
            return

        group = user_groups[user_id]
        tomorrow = datetime.now() + timedelta(days=1)
        day_name = DAY_MAP[tomorrow.weekday()]

        if day_name in ["Субота", "Неділя"]:
            await message.answer(f"➡️ <b>Завтра ({day_name})</b>\n\nВихідний! Пар немає 🎉")
            return

        df = get_schedule_for_group(group, day_name)
        text = format_schedule(df, title=f"➡️ Завтра — {day_name} ({group})")
        await message.answer(text, disable_web_page_preview=True)

    # ========== Тиждень ==========
    @dp.message(F.text == "🗓 Тиждень")
    async def week_schedule(message: Message):
        user_id = message.from_user.id
        if user_id not in user_groups:
            await message.answer("Спочатку обери групу:", reply_markup=groups_keyboard())
            return

        group = user_groups[user_id]
        df = get_schedule_for_group(group)
        text = format_schedule(df, title=f"🗓 Розклад на тиждень ({group})")
        await message.answer(text, disable_web_page_preview=True)

    # ========== Вибрати день ==========
    @dp.message(F.text == "📆 Вибрати день")
    async def choose_day(message: Message):
        user_id = message.from_user.id
        if user_id not in user_groups:
            await message.answer("Спочатку обери групу:", reply_markup=groups_keyboard())
            return

        await message.answer("Обери день:", reply_markup=days_keyboard())

    @dp.callback_query(F.data.startswith("day:"))
    async def process_day(callback: CallbackQuery):
        user_id = callback.from_user.id
        if user_id not in user_groups:
            await callback.answer("Спочатку обери групу", show_alert=True)
            return

        day = callback.data.split(":")[1]
        group = user_groups[user_id]
        df = get_schedule_for_group(group, day)
        text = format_schedule(df, title=f"📆 {day} ({group})")

        await callback.message.edit_text(text, disable_web_page_preview=True)
        await callback.answer()

    @dp.callback_query(F.data == "back_to_menu")
    async def back_to_menu(callback: CallbackQuery):
        await callback.message.delete()
        await callback.answer()

    # ========== Змінити групу ==========
    @dp.message(F.text == "🔄 Змінити групу")
    async def change_group(message: Message, state: FSMContext):
        await message.answer(
            "Обери нову групу:",
            reply_markup=groups_keyboard()
        )
        await state.set_state(Form.waiting_for_group)

    # ========== Запуск ==========
    logger.info("Бот запускається...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
