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
    url = url.strip()
    if "output=csv" in url or "export?format=csv" in url:
        return url
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


def parse_simple_csv(text: str) -> pd.DataFrame:
    """Парсит чистую таблицу"""
    df = pd.read_csv(StringIO(text), dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    # Приводим названия колонок к стандартным
    rename = {}
    for col in df.columns:
        c = col.lower()
        if "група" in c:
            rename[col] = "Група"
        elif "підгруп" in c or "подгруп" in c:
            rename[col] = "Підгрупа"
        elif "день" in c:
            rename[col] = "День"
        elif "час" in c:
            rename[col] = "Час"
        elif "предмет" in c:
            rename[col] = "Предмет"
        elif c == "вид":
            rename[col] = "Вид"
        elif "виклад" in c:
            rename[col] = "Викладач"
        elif "аудит" in c:
            rename[col] = "Аудиторія"
        elif "посилан" in c:
            rename[col] = "Посилання"
        elif "приміт" in c:
            rename[col] = "Примітка"

    df = df.rename(columns=rename)

    # Гарантируем наличие всех нужных колонок
    for col in ["Група", "Підгрупа", "День", "Час", "Предмет", "Вид", "Викладач", "Аудиторія", "Посилання", "Примітка"]:
        if col not in df.columns:
            df[col] = ""

    # Убираем полностью пустые строки
    df = df.fillna("")
    df = df[df["Група"].astype(str).str.strip() != ""]
    df = df[df["День"].astype(str).str.strip() != ""]

    # Оставляем только нужные группы
    df = df[df["Група"].isin(GROUPS)]

    # Сбрасываем индекс, чтобы не было проблем с дубликатами
    df = df.reset_index(drop=True)

    logger.info(f"Простая таблица загружена: {len(df)} записей")
    return df[["Група", "Підгрупа", "День", "Час", "Предмет", "Вид", "Викладач", "Аудиторія", "Посилання", "Примітка"]]


def fetch_and_parse_schedule(url: str | None = None, force: bool = False) -> pd.DataFrame:
    if url is None:
        url = bot_data.get("schedule_url", DEFAULT_SCHEDULE_URL)
    try:
        text = download_raw(url)
        # Проверяем, что это наша простая таблица
        first_line = text.split("\n")[0].lower()
        if "група" in first_line:
            return parse_simple_csv(text)
        else:
            logger.warning("Это не простая таблица")
            return pd.DataFrame()
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


def get_schedule_for_group(group: str, subgroup: str | None = None, day: str | None = None) -> pd.DataFrame:
    df = get_schedule_df()
    if df.empty:
        return df

    df = df[df["Група"] == group].copy()

    if subgroup:
        # Общие (*) + конкретная подгруппа
        subg = df["Підгрупа"].astype(str).str.strip()
        mask = (subg == "") | (subg == "*") | (subg == str(subgroup))
        df = df[mask]

    if day:
        df = df[df["День"] == day]

    return df.sort_values(by=["День", "Час"]).reset_index(drop=True)


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
        subg = str(row.get("Підгрупа", "")).strip()

        kind_emoji = "📘" if kind == "Л" else "🔬" if "лаб" in str(kind).lower() else "📗" if kind == "Пр" else "📕"
        line = f"{kind_emoji} <b>{time}</b> — {subject}"
        if kind:
            line += f" ({kind})"
        if subg and subg not in ("", "*"):
            line += f" [підгр. {subg}]"
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
