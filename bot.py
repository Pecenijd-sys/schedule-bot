import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, DAY_MAP, ADMIN_ID
from data import (
    get_schedule_for_group,
    format_schedule,
    set_schedule_url,
    bot_data,
    save_bot_data,
    get_schedule_df,
)
from keyboards import groups_keyboard, subgroups_keyboard, main_menu_keyboard, days_keyboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Form(StatesGroup):
    waiting_for_group = State()
    waiting_for_subgroup = State()


def get_user_data(user_id: int) -> dict:
    return bot_data.get("user_groups", {}).get(str(user_id), {})


def set_user_data(user_id: int, group: str = None, subgroup: str = None):
    key = str(user_id)
    if key not in bot_data.setdefault("user_groups", {}):
        bot_data["user_groups"][key] = {}
    if group is not None:
        bot_data["user_groups"][key]["group"] = group
    if subgroup is not None:
        bot_data["user_groups"][key]["subgroup"] = subgroup
    save_bot_data(bot_data)


def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


async def reminder_loop(bot: Bot):
    sent_reminders = set()
    while True:
        try:
            now = datetime.now(ZoneInfo("Europe/Kyiv"))
            current_day = DAY_MAP.get(now.weekday(), "")
            if current_day in ["Субота", "Неділя"]:
                await asyncio.sleep(60)
                continue

            if now.hour == 0 and now.minute < 2:
                sent_reminders.clear()

            df = get_schedule_df()
            if df.empty:
                await asyncio.sleep(60)
                continue

            for user_id_str, udata in bot_data.get("user_groups", {}).items():
                user_id = int(user_id_str)
                group = udata.get("group")
                subgroup = udata.get("subgroup")
                if not group:
                    continue

                user_df = get_schedule_for_group(group, subgroup=subgroup, day=current_day)

                for _, row in user_df.iterrows():
                    time_str = row["Час"]
                    try:
                        start_str = time_str.split("-")[0].strip()
                        hour, minute = map(int, start_str.split(":"))
                        pair_start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        # already timezone-aware
                    except Exception:
                        continue

                    key = (user_id, time_str, current_day)
                    if key in sent_reminders:
                        continue

                    diff = (pair_start - now).total_seconds()
                    if 240 <= diff <= 360:
                        subject = row["Предмет"]
                        kind = row.get("Вид", "")
                        teacher = row.get("Викладач", "")
                        link = row.get("Посилання", "")

                        text = f"⏰ <b>Через 5 хвилин починається пара!</b>\n\n📘 <b>{subject}</b>"
                        if kind:
                            text += f" ({kind})"
                        text += f"\n🕒 {time_str}"
                        if teacher:
                            text += f"\n👤 {teacher}"
                        if link and str(link).startswith("http"):
                            text += f"\n🔗 <a href='{link}'>Посилання</a>"

                        try:
                            await bot.send_message(user_id, text, disable_web_page_preview=True)
                            sent_reminders.add(key)
                        except Exception as e:
                            logger.warning(f"Не удалось отправить напоминание: {e}")

        except Exception as e:
            logger.error(f"Ошибка reminder_loop: {e}")

        await asyncio.sleep(60)


async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext):
        udata = get_user_data(message.from_user.id)
        if udata.get("group") and udata.get("subgroup"):
            await message.answer(
                f"Привіт! 👋\n"
                f"Група: <b>{udata['group']}</b>\n"
                f"Підгрупа: <b>{udata['subgroup']}</b>\n\n"
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

    @dp.callback_query(F.data.startswith("group:"))
    async def process_group(callback: CallbackQuery, state: FSMContext):
        group = callback.data.split(":")[1]
        set_user_data(callback.from_user.id, group=group)
        await state.set_state(Form.waiting_for_subgroup)
        await callback.message.edit_text(
            f"Група <b>{group}</b> вибрана.\n\nТепер обери підгрупу:",
            reply_markup=subgroups_keyboard(group)
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("subgroup:"))
    async def process_subgroup(callback: CallbackQuery, state: FSMContext):
        subgroup = callback.data.split(":")[1]
        set_user_data(callback.from_user.id, subgroup=subgroup)
        await state.clear()
        udata = get_user_data(callback.from_user.id)
        await callback.message.edit_text(
            f"✅ Збережено!\n\n"
            f"Група: <b>{udata.get('group')}</b>\n"
            f"Підгрупа: <b>{subgroup}</b>\n\n"
            "Тепер користуйся меню нижче 👇"
        )
        await callback.message.answer("Обери дію:", reply_markup=main_menu_keyboard())
        await callback.answer()

    @dp.message(F.text == "📅 Сьогодні")
    async def today_schedule(message: Message):
        udata = get_user_data(message.from_user.id)
        if not udata.get("group"):
            await message.answer("Спочатку обери групу:", reply_markup=groups_keyboard())
            return
        today = datetime.now(ZoneInfo("Europe/Kyiv"))
        day_name = DAY_MAP[today.weekday()]
        if day_name in ["Субота", "Неділя"]:
            await message.answer(f"📅 <b>Сьогодні ({day_name})</b>\n\nВихідний! 🎉")
            return
        df = get_schedule_for_group(udata["group"], subgroup=udata.get("subgroup"), day=day_name)
        text = format_schedule(df, title=f"📅 Сьогодні — {day_name} ({udata['group']}, підгр. {udata.get('subgroup')})")
        await message.answer(text, disable_web_page_preview=True)

    @dp.message(F.text == "➡️ Завтра")
    async def tomorrow_schedule(message: Message):
        udata = get_user_data(message.from_user.id)
        if not udata.get("group"):
            await message.answer("Спочатку обери групу:", reply_markup=groups_keyboard())
            return
        tomorrow = datetime.now(ZoneInfo("Europe/Kyiv")) + timedelta(days=1)
        day_name = DAY_MAP[tomorrow.weekday()]
        if day_name in ["Субота", "Неділя"]:
            await message.answer(f"➡️ <b>Завтра ({day_name})</b>\n\nВихідний! 🎉")
            return
        df = get_schedule_for_group(udata["group"], subgroup=udata.get("subgroup"), day=day_name)
        text = format_schedule(df, title=f"➡️ Завтра — {day_name} ({udata['group']}, підгр. {udata.get('subgroup')})")
        await message.answer(text, disable_web_page_preview=True)

    @dp.message(F.text == "🗓 Тиждень")
    async def week_schedule(message: Message):
        udata = get_user_data(message.from_user.id)
        if not udata.get("group"):
            await message.answer("Спочатку обери групу:", reply_markup=groups_keyboard())
            return
        df = get_schedule_for_group(udata["group"], subgroup=udata.get("subgroup"))
        text = format_schedule(df, title=f"🗓 Розклад ({udata['group']}, підгр. {udata.get('subgroup')})")
        await message.answer(text, disable_web_page_preview=True)

    @dp.message(F.text == "📆 Вибрати день")
    async def choose_day(message: Message):
        if not get_user_data(message.from_user.id).get("group"):
            await message.answer("Спочатку обери групу:", reply_markup=groups_keyboard())
            return
        await message.answer("Обери день:", reply_markup=days_keyboard())

    @dp.callback_query(F.data.startswith("day:"))
    async def process_day(callback: CallbackQuery):
        udata = get_user_data(callback.from_user.id)
        if not udata.get("group"):
            await callback.answer("Спочатку обери групу", show_alert=True)
            return
        day = callback.data.split(":")[1]
        df = get_schedule_for_group(udata["group"], subgroup=udata.get("subgroup"), day=day)
        text = format_schedule(df, title=f"📆 {day} ({udata['group']}, підгр. {udata.get('subgroup')})")
        await callback.message.edit_text(text, disable_web_page_preview=True)
        await callback.answer()

    @dp.callback_query(F.data == "back_to_menu")
    async def back_to_menu(callback: CallbackQuery):
        await callback.message.delete()
        await callback.answer()

    @dp.message(F.text == "🔄 Змінити групу")
    async def change_group(message: Message, state: FSMContext):
        await message.answer("Обери групу:", reply_markup=groups_keyboard())
        await state.set_state(Form.waiting_for_group)

    @dp.message(Command("set_schedule"))
    async def cmd_set_schedule(message: Message):
        if not is_admin(message.from_user.id):
            await message.answer("⛔ Тільки для адміністратора.")
            return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Використання:\n<code>/set_schedule посилання</code>")
            return
        url = parts[1].strip()
        await message.answer("⏳ Завантажую таблицю...")
        ok = set_schedule_url(url)
        if ok:
            await message.answer("✅ Розклад успішно оновлено!")
        else:
            await message.answer("⚠️ Не вдалося завантажити або розпарсити таблицю.")

    @dp.message(Command("myid"))
    async def cmd_myid(message: Message):
        await message.answer(f"Твій ID: <code>{message.from_user.id}</code>")

    logger.info("Бот запускається...")
    asyncio.create_task(reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
