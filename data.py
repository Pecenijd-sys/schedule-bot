import re
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from io import StringIO

import pandas as pd
import requests

from config import DEFAULT_SCHEDULE_URL, GROUPS, DATA_FILE, DAY_MAP

logger = logging.getLogger(__name__)

# === Хранение данных ===
def load_bot_data() -> dict:
    path = Path(DATA_FILE)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "schedule_url": DEFAULT_SCHEDULE_URL,
        "user_groups": {},
        "reminders_enabled": {},
    }

def save_bot_data(data: dict):
    Path(DATA_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

bot_data = load_bot_data()


def fetch_and_parse_schedule(url: str | None = None) -> pd.DataFrame:
    """Скачивает и парсит оригинальную сложную таблицу университета"""
    if url is None:
        url = bot_data.get("schedule_url", DEFAULT_SCHEDULE_URL)

    # Приводим ссылку к CSV-экспорту
    if "/edit" in url or "docs.google.com/spreadsheets" in url:
        match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
        gid_match = re.search(r"gid=(\d+)", url)
        if match:
            sheet_id = match.group(1)
            gid = gid_match.group(1) if gid_match else "0"
            url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

    logger.info(f"Загружаю расписание: {url}")

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        content = resp.content.decode("utf-8", errors="replace")
        df = pd.read_csv(StringIO(content), header=None, dtype=str).fillna("")
    except Exception as e:
        logger.error(f"Ошибка загрузки таблицы: {e}")
        return pd.DataFrame()

    group_cols = {
        "ІПЗ-11": list(range(2, 8)),
        "ІПЗ-12": list(range(8, 14)),
        "ІПЗ-13": list(range(14, 20)),
        "ІПЗ-14": list(range(20, 24)),
    }

    rows = []
    current_day = ""
    i = 4
    while i < min(len(df), 400):
        day_raw = str(df.iloc[i, 0]).strip().lower()
        time = str(df.iloc[i, 1]).strip()

        if day_raw in ["понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота"]:
            day_map = {
                "понеділок": "Понеділок",
                "вівторок": "Вівторок",
                "середа": "Середа",
                "четвер": "Четвер",
                "п'ятниця": "П'ятниця",
                "субота": "Субота",
            }
            current_day = day_map.get(day_raw, day_raw)

        if time and re.match(r"\d{1,2}:\d{2}-\d{1,2}:\d{2}", time):
            for group, cols in group_cols.items():
                subjects = []
                for col in cols:
                    val = str(df.iloc[i, col]).strip()
                    if val and len(val) > 3 and not val.isdigit():
                        subjects.append(val)

                if not subjects:
                    continue

                teacher = ""
                link = ""
                note = ""
                for k in range(i + 1, min(i + 7, len(df))):
                    for col in cols:
                        val = str(df.iloc[k, col]).strip()
                        if not val:
                            continue
                        if val.startswith("[") and "]" in val:
                            note = val
                        elif any(x in val.lower() for x in ["http", "zoom.us", "meet.google", "teams.microsoft"]):
                            if not link:
                                link = val.split()[0]
                        elif (
                            len(val) > 4
                            and not re.match(r"^\d", val)
                            and "ауд" not in val.lower()
                            and "підгр" not in val.lower()
                        ):
                            if not teacher:
                                teacher = val

                for subj in subjects:
                    kind = ""
                    if "(Л)" in subj:
                        kind = "Л"
                    elif "лаб" in subj.lower():
                        kind = "лаб"
                    elif "(Пр)" in subj or "Пр)" in subj:
                        kind = "Пр"

                    clean_subj = re.sub(r"\s*\([^)]*\)\s*", "", subj).strip()
                    clean_subj = re.sub(r"\s*\[.*?\]\s*", "", clean_subj).strip()

                    rows.append({
                        "Група": group,
                        "День": current_day,
                        "Час": time,
                        "Предмет": clean_subj,
                        "Вид": kind,
                        "Викладач": teacher,
                        "Аудиторія": "",
                        "Посилання": link,
                        "Примітка": note,
                    })
        i += 1

    if not rows:
        logger.warning("Не удалось извлечь пары из таблицы")
        return pd.DataFrame()

    result = pd.DataFrame(rows)
    result = result.drop_duplicates(subset=["Група", "День", "Час", "Предмет"])
    logger.info(f"Извлечено {len(result)} записей")
    return result


_schedule_cache: pd.DataFrame | None = None
_cache_time: datetime | None = None

def get_schedule_df(force: bool = False) -> pd.DataFrame:
    global _schedule_cache, _cache_time
    now = datetime.now()
    if (
        not force
        and _schedule_cache is not None
        and _cache_time
        and (now - _cache_time) < timedelta(minutes=30)
    ):
        return _schedule_cache

    _schedule_cache = fetch_and_parse_schedule()
    _cache_time = now
    return _schedule_cache


def get_schedule_for_group(group: str, day: str | None = None) -> pd.DataFrame:
    df = get_schedule_df()
    if df.empty:
        return df
    df = df[df["Група"] == group].copy()
    if day:
        df = df[df["День"] == day]
    return df.sort_values(by="Час")


def format_schedule(df: pd.DataFrame, title: str = "") -> str:
    if df.empty:
        return f"{title}\n\nНа цей день пар немає 🎉" if title else "На цей день пар немає 🎉"

    lines = []
    if title:
        lines.append(f"<b>{title}</b>\n")

    current_day = None
    for _, row in df.iterrows():
        day = row["День"]
        if day != current_day:
            if current_day is not None:
                lines.append("")
            lines.append(f"📅 <b>{day}</b>")
            current_day = day

        time = row["Час"]
        subject = row["Предмет"]
        kind = row.get("Вид", "")
        teacher = row.get("Викладач", "")
        link = row.get("Посилання", "")
        note = row.get("Примітка", "")

        kind_emoji = "📘" if kind == "Л" else "🔬" if kind == "лаб" else "📗" if kind == "Пр" else "📕"
        line = f"{kind_emoji} <b>{time}</b> — {subject}"
        if kind:
            line += f" ({kind})"
        lines.append(line)

        if teacher:
            lines.append(f"   👤 {teacher}")
        if link:
            lines.append(f"   🔗 <a href='{link}'>Посилання на пару</a>")
        if note:
            lines.append(f"   📌 {note}")

    return "\n".join(lines)


def set_schedule_url(url: str) -> bool:
    global _schedule_cache, _cache_time
    bot_data["schedule_url"] = url
    save_bot_data(bot_data)
    _schedule_cache = None
    _cache_time = None
    df = get_schedule_df(force=True)
    return not df.empty
