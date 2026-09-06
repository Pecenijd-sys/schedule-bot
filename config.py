import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен! Добавь его в переменные окружения.")

# ID администратора (только он может менять ссылку на расписание)
# Узнать свой ID можно у бота @userinfobot
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Ссылка на Google Таблицу по умолчанию
DEFAULT_SCHEDULE_URL = os.getenv(
    "SCHEDULE_URL",
    "https://docs.google.com/spreadsheets/d/13rZhY4OYmWwwGfWaOJg4Maw7erKvnihlO79yJ1ZBkvg/export?format=csv&gid=952362142"
)

# Группы
GROUPS = ["ІПЗ-11", "ІПЗ-12", "ІПЗ-13", "ІПЗ-14"]

# Дни недели
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

# Файл для хранения настроек и групп пользователей
DATA_FILE = "bot_data.json"
