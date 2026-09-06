import re
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from io import StringIO

import pandas as pd
import requests

from config import DEFAULT_SCHEDULE_URL, GROUPS, DATA_FILE, DAY_MAP, XAI_API_KEY

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
        "ai_cache": None,
        "ai_cache_time": None,
    }

def save_bot_data(data: dict):
    Path(DATA_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

bot_data = load_bot_data()


def normalize_url(url: str) -> str:
    """Приводит ссылку Google Sheets к CSV-экспорту"""
    if "/edit" in url or "docs.google.com/spreadsheets" in url:
        match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
        gid_match = re.search(r"gid=(\d+)", url)
        if match:
            sheet_id = match.group(1)
            gid = gid_match.group(1) if gid_match else "0"
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    return url


def download_csv(url: str) -> str:
    url = normalize_url(url)
    logger.info(f"Скачиваю таблицу: {url}")
    resp = requests.get(url, timeout=40)
    resp.raise_for_status()
    return resp.content.decode("utf-8", errors="replace")


def parse_with_ai(csv_text: str) -> list[dict]:
    """Отправляет таблицу в Grok и получает структурированное расписание"""
    if not XAI_API_KEY:
        logger.error("XAI_API_KEY не задан")
        return []

    # Обрезаем слишком длинный CSV (оставляем первые ~120к символов — обычно хватает)
    if len(csv_text) > 120000:
        csv_text = csv_text[:120000] + "\n...[обрезано]..."

    system_prompt = """Ты — эксперт по разбору университетских расписаний.
Тебе дают сырой CSV из сложной Google-таблицы расписания 1 курса ІПЗ (КНУ).

Твоя задача — максимально точно извлечь ВСЕ занятия для групп ІПЗ-11, ІПЗ-12, ІПЗ-13, ІПЗ-14.

Правила:
1. Включай и лекции (Л), и лабораторные (лаб), и практики (Пр).
2. Если занятие общее для нескольких групп/подгрупп — продублируй его для каждой группы.
3. Старайся вытащить преподавателя и ссылку (Zoom / Meet / Teams), даже если ссылка написана коротко (teams, knu-ua.zoom, zoom).
4. Если ссылка короткая — оставляй как есть (например "teams" или "knu-ua.zoom").
5. Дни пиши украинским: Понеділок, Вівторок, Середа, Четвер, П'ятниця.
6. Время в формате 9:00-10:20 или 10:30-11:50 и т.д.
7. Игнорируй іноземну мову, если она явно только для отдельных подгрупп и не нужна потоку (но если сомневаешься — лучше включи).

Верни ТОЛЬКО валидный JSON-массив объектов. Никакого текста до или после.
Формат каждого объекта:
{
  "group": "ІПЗ-11",
  "day": "Вівторок",
  "time": "9:00-10:20",
  "subject": "Математичні основи програмної інженерії",
  "kind": "Л",
  "teacher": "Ковтун О. І.",
  "link": "https://...",
  "note": ""
}

Если чего-то нет — оставляй пустую строку.
Старайся вытащить максимум реальных занятий."""

    user_prompt = f"Вот CSV таблицы расписания:\n\n{csv_text}"

    try:
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-4-fast-non-reasoning",  # быстрый и дешёвый
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
            },
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()

        # Убираем возможные ```json обёртки
        content = re.sub(r"^```json\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        result = json.loads(content)
        if isinstance(result, list):
            logger.info(f"ИИ извлёк {len(result)} занятий")
            return result
        else:
            logger.error("ИИ вернул не список")
            return []
    except Exception as e:
        logger.error(f"Ошибка ИИ-парсинга: {e}")
        return []


def fetch_and_parse_schedule(url: str | None = None, force: bool = False) -> pd.DataFrame:
    """Главная функция: скачивает + парсит через ИИ (с кэшем)"""
    if url is None:
        url = bot_data.get("schedule_url", DEFAULT_SCHEDULE_URL)

    # Проверяем кэш (2 часа)
    cache = bot_data.get("ai_cache")
    cache_time_str = bot_data.get("ai_cache_time")
    if not force and cache and cache_time_str:
        try:
            cache_time = datetime.fromisoformat(cache_time_str)
            if datetime.now() - cache_time < timedelta(hours=2):
                logger.info("Использую кэш ИИ-парсинга")
                return pd.DataFrame(cache)
        except Exception:
            pass

    try:
        csv_text = download_csv(url)
        items = parse_with_ai(csv_text)

        if not items:
            logger.warning("ИИ ничего не вернул")
            return pd.DataFrame()

        # Нормализуем
        rows = []
        for item in items:
            rows.append({
                "Група": item.get("group", "").strip(),
                "День": item.get("day", "").strip(),
                "Час": item.get("time", "").strip(),
                "Предмет": item.get("subject", "").strip(),
                "Вид": item.get("kind", "").strip(),
                "Викладач": item.get("teacher", "").strip(),
                "Аудиторія": "",
                "Посилання": item.get("link", "").strip(),
                "Примітка": item.get("note", "").strip(),
            })

        df = pd.DataFrame(rows)
        df = df[df["Група"].isin(GROUPS)]
        df = df.drop_duplicates(subset=["Група", "День", "Час", "Предмет"])

        # Сохраняем в кэш
        bot_data["ai_cache"] = rows
        bot_data["ai_cache_time"] = datetime.now().isoformat()
        save_bot_data(bot_data)

        logger.info(f"Успешно получено {len(df)} записей через ИИ")
        return df

    except Exception as e:
        logger.error(f"Ошибка получения расписания: {e}")
        return pd.DataFrame()


# Кэш в памяти
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

        kind_emoji = "📘" if kind == "Л" else "🔬" if "лаб" in str(kind).lower() else "📗" if kind == "Пр" else "📕"
        line = f"{kind_emoji} <b>{time}</b> — {subject}"
        if kind:
            line += f" ({kind})"
        lines.append(line)

        if teacher:
            lines.append(f"   👤 {teacher}")
        if link:
            if link.startswith("http"):
                lines.append(f"   🔗 <a href='{link}'>Посилання на пару</a>")
            else:
                lines.append(f"   🔗 {link}")
        if note:
            lines.append(f"   📌 {note}")

    return "\n".join(lines)


def set_schedule_url(url: str) -> bool:
    global _schedule_cache, _cache_time
    bot_data["schedule_url"] = url
    bot_data["ai_cache"] = None
    bot_data["ai_cache_time"] = None
    save_bot_data(bot_data)
    _schedule_cache = None
    _cache_time = None
    df = get_schedule_df(force=True)
    return not df.empty
