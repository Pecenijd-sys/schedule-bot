import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен! Добавь его в переменные окружения.")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Оригинальная таблица университета (для XLSX-парсера)
DEFAULT_SCHEDULE_URL = os.getenv(
    "SCHEDULE_URL",
    "https://docs.google.com/spreadsheets/d/13rZhY4OYmWwwGfWaOJg4Maw7erKvnihlO79yJ1ZBkvg/edit"
)

# Группы в том виде, как их извлекает парсер
GROUPS = [
    "група ІПЗ-11",
    "група ІПЗ-12",
    "група ІПЗ-13",
    "група ІПЗ-14",
]

DAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця"]
DAY_MAP = {
    0: "Понеділок",
    1: "Вівторок",
    2: "Середа",
    3: "Четвер",
    4: "П'ятниця",
    5: "Субота",
    6: "Неділя",
}

DATA_FILE = "bot_data.json"
