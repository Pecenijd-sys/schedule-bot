from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from config import DAYS


# Короткие имена для UI и полные для хранения
GROUP_OPTIONS = [
    ("ІПЗ-11", "група ІПЗ-11"),
    ("ІПЗ-12", "група ІПЗ-12"),
    ("ІПЗ-13", "група ІПЗ-13"),
    ("ІПЗ-14", "група ІПЗ-14"),
]

# Реальные подгруппы по коротким именам групп
SUBGROUPS_MAP = {
    "група ІПЗ-11": [(1, 1), (2, 2), (3, 3)],
    "група ІПЗ-12": [(4, 1), (5, 2), (6, 3)],
    "група ІПЗ-13": [(7, 1), (8, 2), (9, 3)],
    "група ІПЗ-14": [(10, 1), (11, 2)],
    # на всякий случай и короткие ключи
    "ІПЗ-11": [(1, 1), (2, 2), (3, 3)],
    "ІПЗ-12": [(4, 1), (5, 2), (6, 3)],
    "ІПЗ-13": [(7, 1), (8, 2), (9, 3)],
    "ІПЗ-14": [(10, 1), (11, 2)],
}


def groups_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for short, full in GROUP_OPTIONS:
        builder.button(text=short, callback_data=f"group:{full}")
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
