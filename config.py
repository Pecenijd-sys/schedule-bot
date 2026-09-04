import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8894720454:AAE1HLsy4MpYQEztIOkhFoFsWCYp5nme1VA")

# Путь к чистому расписанию
SCHEDULE_FILE = "schedule_clean_IPZ11-14.csv"

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
