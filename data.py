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


def normalize_url(url: str) -> str:
    """Нормализует ссылку Google Sheets к CSV"""
    url = url.strip()

    # Уже готовый pub?output=csv
    if "output=csv" in url or "export?format=csv" in url:
        return url

    # Обычная edit-ссылка
    if "docs.google.com/spreadsheets" in url:
        match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
        gid_match = re.search(r"gid=(\d+)", url)
        if match:
            sheet_id = match.group(1)
            gid = gid_match.group(1) if gid_match else "0"
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

    return url


def download_raw(url: str) -> str:
    url = normalize_url(url)
    logger.info(f"Скачиваю: {url}")
    resp = requests.get(url, timeout=40)
    resp.raise_for_status()
    return resp.content.decode("utf-8", errors="replace")


def is_simple_table(text: str) -> bool:
    """Проверяет, похоже ли на нашу простую таблицу"""
    first_line = text.split("\n")[0].lower()
    return "група" in first_line and "день" in first_line and "час" in first_line


def parse_simple_csv(text: str) -> pd.DataFrame:
    """Парсит чистую таблицу с заголовками"""
    df = pd.read_csv(StringIO(text), dtype=str).fillna("")
    # Нормализуем названия колонок
    col_map = {}
    for col in df.columns:
        c = col.strip().lower()
        if "група" in c:
            col_map[col] = "Група"
        elif "день" in c:
            col_map[col] = "День"
        elif "час" in c or "час" in c:
            col_map[col] = "Час"
        elif "предмет" in c:
            col_map[col] = "Предмет"
        elif "вид" in c:
            col_map[col] = "Вид"
        elif "виклад" in c:
            col_map[col] = "Викладач"
        elif "аудит" in c:
            col_map[col] = "Аудиторія"
        elif "посилан" in c or "link" in c:
            col_map[col] = "Посилання"
        elif "приміт" in c or "note" in c:
            col_map[col] = "Примітка"

    df = df.rename(columns=col_map)

    # Оставляем только нужные колонки
    needed = ["Група", "День", "Час", "Предмет", "Вид", "Викладач", "Аудиторія", "Посилання", "Примітка"]
    for col in needed:
        if col not in df.columns:
            df[col] = ""

    df = df[needed]
    df = df[df["Група"].isin(GROUPS)]
    df = df[df["День"] != ""]
    df = df[df["Час"] != ""]
    logger.info(f"Простая таблица: {len(df)} записей")
    return df


def parse_complex_schedule(df: pd.DataFrame) -> list[dict]:
    """Старый парсер сложной таблицы (на всякий случай)"""
    rows = []
    current_day = ""
    max_col = min(df.shape[1], 30)

    GROUP_RANGES = {
        "ІПЗ-11": (2, 8),
        "ІПЗ-12": (8, 14),
        "ІПЗ-13": (14, 20),
        "ІПЗ-14": (20, 24),
    }

    def is_time(s):
        return bool(re.match(r"^\d{1,2}:\d{2}-\d{1,2}:\d{2}$", str(s).strip()))

    def is_day(s):
        return str(s).strip().lower() in ["понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота"]

    i = 0
    while i < len(df):
        day_cell = str(df.iloc[i, 0]).strip().lower()
        if is_day(day_cell):
            day_map = {
                "понеділок": "Понеділок", "вівторок": "Вівторок", "середа": "Середа",
                "четвер": "Четвер", "п'ятниця": "П'ятниця", "субота": "Субота"
            }
            current_day = day_map.get(day_cell, day_cell)

        time_cell = str(df.iloc[i, 1]).strip()
        if not is_time(time_cell):
            i += 1
            continue

        for group, (c_start, c_end) in GROUP_RANGES.items():
            subjects = []
            for col in range(c_start, min(c_end, max_col)):
                val = str(df.iloc[i, col]).strip()
                if val and len(val) > 4 and not val.isdigit() and not is_time(val):
                    subjects.append(val)

            if not subjects:
                continue

            teacher = ""
            link = ""
            for k in range(i + 1, min(i + 6, len(df))):
                for col in range(c_start, min(c_end, max_col)):
                    val = str(df.iloc[k, col]).strip()
                    if not val:
                        continue
                    if any(x in val.lower() for x in ["http", "zoom", "meet.", "teams"]) and not link:
                        m = re.search(r"(https?://[^\s]+)", val)
                        link = m.group(1) if m else val
                    elif re.search(r"[А-ЯІЇЄҐ][а-яіїєґ']+", val) and len(val) < 50 and not teacher:
                        teacher = val

            for subj in subjects:
                kind = "Л" if "(Л)" in subj else ("лаб" if "лаб" in subj.lower() else ("Пр" if "Пр" in subj else ""))
                clean = re.sub(r"\s*\([^)]*\)\s*", " ", subj)
                clean = re.sub(r"\s*\[.*?\]\s*", " ", clean).strip()
                rows.append({
                    "Група": group, "День": current_day, "Час": time_cell,
                    "Предмет": clean, "Вид": kind, "Викладач": teacher,
                    "Аудиторія": "", "Посилання": link, "Примітка": ""
                })
        i += 1

    return rows


def fetch_and_parse_schedule(url: str | None = None, force: bool = False) -> pd.DataFrame:
    if url is None:
        url = bot_data.get("schedule_url", DEFAULT_SCHEDULE_URL)

    try:
        text = download_raw(url)

        if is_simple_table(text):
            return parse_simple_csv(text)
        else:
            # Сложная таблица
            df_raw = pd.read_csv(StringIO(text), header=None, dtype=str).fillna("")
            items = parse_complex_schedule(df_raw)
            if not items:
                return pd.DataFrame()
            return pd.DataFrame(items)

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return pd.DataFrame()


_schedule_cache = None
_cache_time = None

def get_schedule_df(force: bool = False) -> pd.DataFrame:
    global _schedule_cache, _cache_time
    now = datetime.now()
    if not force and _schedule_cache is not None and _cache_time and (now - _cache_time) < timedelta(minutes=30):
        return _schedule_cache
    _schedule_cache = fetch_and_parse_schedule(force=force)
    _cache_time = now
    return _schedule_cache


def get_schedule_for_group(group: str, day: str | None = None) -> pd.DataFrame:
    df = get_schedule_df()
    if df.empty:
        return df
    df = df[df["Група"] == group].copy()
    if day:
        df = df[df["День"] == day]
    return df.sort_values(by=["День", "Час"])


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

        kind_emoji = "📘" if kind == "Л" else "🔬" if "лаб" in str(kind).lower() else "📗" if kind == "Пр" else "📕"
        line = f"{kind_emoji} <b>{time}</b> — {subject}"
        if kind:
            line += f" ({kind})"
        lines.append(line)

        if teacher:
            lines.append(f"   👤 {teacher}")
        if link:
            if str(link).startswith("http"):
                lines.append(f"   🔗 <a href='{link}'>Посилання</a>")
            else:
                lines.append(f"   🔗 {link}")
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
