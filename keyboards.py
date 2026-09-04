from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from config import GROUPS, DAYS


def groups_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for group in GROUPS:
        builder.button(text=group, callback_data=f"group:{group}")
    builder.adjust(2)
    return builder.as_markup()


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="📅 Сьогодні")
    builder.button(text="➡️ Завтра")
    builder.button(text="🗓 Тиждень")
    builder.button(text="📆 Вибрати день")
    builder.button(text="🔄 Змінити групу")
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def days_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for day in DAYS:
        builder.button(text=day, callback_data=f"day:{day}")
    builder.button(text="« Назад", callback_data="back_to_menu")
    builder.adjust(2)
    return builder.as_markup()
