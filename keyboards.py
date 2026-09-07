from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from config import GROUPS, DAYS


# Реальные подгруппы по группам
SUBGROUPS_MAP = {
    "ІПЗ-11": [(1, 1), (2, 2), (3, 3)],
    "ІПЗ-12": [(4, 1), (5, 2), (6, 3)],
    "ІПЗ-13": [(7, 1), (8, 2), (9, 3)],
    "ІПЗ-14": [(10, 1), (11, 2)],
}


def groups_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for group in GROUPS:
        builder.button(text=group, callback_data=f"group:{group}")
    builder.adjust(2)
    return builder.as_markup()


def subgroups_keyboard(group: str) -> InlineKeyboardMarkup:
    """Показывает подгруппы в зависимости от выбранной группы"""
    builder = InlineKeyboardBuilder()
    items = SUBGROUPS_MAP.get(group, [])
    for real_num, simple_num in items:
        builder.button(
            text=f"{real_num} ({simple_num})",
            callback_data=f"subgroup:{real_num}"
        )
    builder.adjust(3)
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
