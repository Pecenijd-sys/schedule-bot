import re
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from io import StringIO
from collections import defaultdict

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
    if "/edit" in url or "docs.google.com/spreadsheets" in url:
        match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
        gid_match = re.search(r"gid=(\d+)", url)
        if match:
            sheet_id = match.group(1)
            gid = gid_match.group(1) if gid_match else "0"
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    return url


def download_csv(url: str) -> pd.DataFrame:
    url = normalize_url(url)
    logger.info(f"Скачиваю: {url}")
    resp = requests.get(url, timeout=40)
    resp.raise_for_status()
    content = resp.content.decode("utf-8", errors="replace")
    return pd.read_csv(StringIO(content), header=None, dtype=str).fillna("")


def is_time(s: str) -> bool:
    return bool(re.match(r"^\d{1,2}:\d{2}-\d{1,2}:\d{2}$", s.strip()))


def is_day(s: str) -> bool:
    return s.strip().lower() in ["понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота"]


def clean_subject(s: str) -> tuple[str, str]:
    """Возвращает (название, вид)"""
    s = s.strip()
    kind = ""
    if re.search(r"\(Л\)", s, re.I):
        kind = "Л"
    elif re.search(r"лаб", s, re.I):
        kind = "лаб"
    elif re.search(r"\(Пр\)|Пр\)", s, re.I):
        kind = "Пр"
    clean = re.sub(r"\s*\([^)]*\)\s*", " ", s)
    clean = re.sub(r"\s*\[.*?\]\s*", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean, kind


def looks_like_teacher(s: str) -> bool:
    s = s.strip()
    if len(s) < 4 or len(s) > 60:
        return False
    if any(x in s.lower() for x in ["http", "zoom", "meet.", "teams", "ауд", "підгр", "група"]):
        return False
    if re.match(r"^\d", s):
        return False
    # Типичные паттерны украинских ФИО
    if re.search(r"[А-ЯІЇЄҐ][а-яіїєґ']+\s+[А-ЯІЇЄҐ]\.?\s*[А-ЯІЇЄҐ]?\.?", s):
        return True
    if re.search(r"[А-ЯІЇЄҐ][а-яіїєґ']+\s+[А-ЯІЇЄҐ][а-яіїєґ']+", s):
        return True
    return False


def looks_like_link(s: str) -> bool:
    s = s.strip().lower()
    return any(x in s for x in ["http", "zoom.us", "meet.google", "teams.microsoft", "knu-ua.zoom", "teams", "zoom"])


def extract_link(s: str) -> str:
    s = s.strip()
    # Полный URL
    m = re.search(r"(https?://[^\s]+)", s)
    if m:
        return m.group(1)
    # Короткие
    low = s.lower()
    if "teams" in low:
        return "teams"
    if "knu-ua.zoom" in low or "zoom" in low:
        return s
    return s


# Примерные колонки групп (из структуры таблицы)
GROUP_RANGES = {
    "ІПЗ-11": (2, 8),
    "ІПЗ-12": (8, 14),
    "ІПЗ-13": (14, 20),
    "ІПЗ-14": (20, 24),
}


def parse_complex_schedule(df: pd.DataFrame) -> list[dict]:
    rows = []
    current_day = ""
    max_col = min(df.shape[1], 30)

    i = 0
    while i < len(df):
        # День
        day_cell = str(df.iloc[i, 0]).strip().lower()
        if is_day(day_cell):
            day_map = {
                "понеділок": "Понеділок",
                "вівторок": "Вівторок",
                "середа": "Середа",
                "четвер": "Четвер",
                "п'ятниця": "П'ятниця",
                "субота": "Субота",
            }
            current_day = day_map.get(day_cell, day_cell)

        # Время
        time_cell = str(df.iloc[i, 1]).strip()
        if not is_time(time_cell):
            i += 1
            continue

        time = time_cell

        # Собираем предметы по группам
        for group, (c_start, c_end) in GROUP_RANGES.items():
            subjects = []
            for col in range(c_start, min(c_end, max_col)):
                val = str(df.iloc[i, col]).strip()
                if val and len(val) > 4 and not val.isdigit() and not is_time(val):
                    subjects.append((col, val))

            if not subjects:
                continue

            # Ищем преподавателя и ссылку в следующих 1-6 строках в тех же колонках
            teacher = ""
            link = ""
            note = ""

            for k in range(i + 1, min(i + 7, len(df))):
                for col in range(c_start, min(c_end, max_col)):
                    val = str(df.iloc[k, col]).strip()
                    if not val:
                        continue
                    if val.startswith("[") and "]" in val:
                        note = val
                    elif looks_like_link(val) and not link:
                        link = extract_link(val)
                    elif looks_like_teacher(val) and not teacher:
                        teacher = val

            for col, subj_raw in subjects:
                subject, kind = clean_subject(subj_raw)
                if not subject or len(subject) < 3:
                    continue

                rows.append({
                    "Група": group,
                    "День": current_day,
                    "Час": time,
                    "Предмет": subject,
                    "Вид": kind,
                    "Викладач": teacher,
                    "Аудиторія": "",
                    "Посилання": link,
                    "Примітка": note,
                })

        i += 1

    # Убираем дубли
    seen = set()
    unique = []
    for r in rows:
        key = (r["Група"], r["День"], r["Час"], r["Предмет"])
        if key not in seen and r["День"]:
            seen.add(key)
            unique.append(r)

    logger.info(f"Извлечено {len(unique)} занятий")
    return unique


def fetch_and_parse_schedule(url: str | None = None, force: bool = False) -> pd.DataFrame:
    if url is None:
        url = bot_data.get("schedule_url", DEFAULT_SCHEDULE_URL)

    try:
        df_raw = download_csv(url)
        items = parse_complex_schedule(df_raw)
        if not items:
            return pd.DataFrame()
        return pd.DataFrame(items)
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return pd.DataFrame()


_schedule_cache: pd.DataFrame | None = None
_cache_time: datetime | None = None

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
