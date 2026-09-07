import io
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl
import pandas as pd
import requests

from config import DEFAULT_SCHEDULE_URL, GROUPS, DATA_FILE

logger = logging.getLogger(__name__)

# ============================================================
# Хранилище данных бота
# ============================================================

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
    Path(DATA_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


bot_data = load_bot_data()


# ============================================================
# Google Sheets -> XLSX
# ============================================================

def spreadsheet_xlsx_url(url: str) -> str:
    """
    Принимает обычную ссылку Google Sheets:
    https://docs.google.com/spreadsheets/d/<ID>/edit?gid=...

    Возвращает XLSX всего workbook.

    ВАЖНО:
    gid специально НЕ используется.
    Нам нужны все листы workbook, потому что группы находятся
    на разных листах.
    """
    url = url.strip()

    # Уже готовая ссылка на XLSX
    if "export?format=xlsx" in url:
        return url

    match = re.search(
        r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)",
        url,
    )

    if not match:
        return url

    spreadsheet_id = match.group(1)

    return (
        f"https://docs.google.com/spreadsheets/d/"
        f"{spreadsheet_id}/export?format=xlsx"
    )


def download_xlsx(url: str) -> bytes:
    xlsx_url = spreadsheet_xlsx_url(url)

    logger.info("Скачиваю XLSX: %s", xlsx_url)

    response = requests.get(
        xlsx_url,
        timeout=60,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()

    # Если Google вместо XLSX отдал HTML/страницу ошибки,
    # лучше сразу сообщить об этом.
    if "html" in content_type and not response.content.startswith(b"PK"):
        raise RuntimeError(
            "Google Sheets вернул HTML вместо XLSX. "
            "Проверьте доступность таблицы по ссылке."
        )

    return response.content


# ============================================================
# Вспомогательные функции Excel
# ============================================================

TIME_RE = re.compile(
    r"^\s*\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\s*$"
)

DAY_MAP = {
    "понеділок": "Понеділок",
    "вівторок": "Вівторок",
    "середа": "Середа",
    "четвер": "Четвер",
    "п'ятниця": "П'ятниця",
    "п’ятниця": "П'ятниця",
    "субота": "Субота",
}


def clean_text(value) -> str:
    if value is None:
        return ""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    text = str(value)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def normalize_day(value) -> str:
    text = clean_text(value).lower()
    return DAY_MAP.get(text, clean_text(value))


def is_time(value) -> bool:
    return bool(TIME_RE.fullmatch(clean_text(value)))


def split_subject_and_kind(subject: str):
    """
    Например:
      'Основи програмування (Л)' -> ('Основи програмування', 'Л')
      '... (лаб)' -> ('...', 'лаб')
      '... (Пр)' -> ('...', 'Пр')
    """
    subject = clean_text(subject)

    match = re.search(
        r"\s*\((Л|Пр|лаб|Лаб|практ\.?|сем\.?)\)\s*$",
        subject,
        flags=re.IGNORECASE,
    )

    if not match:
        return subject, ""

    kind = match.group(1)
    subject = subject[:match.start()].strip()

    # Нормализуем обозначения
    low = kind.lower()
    if low == "лаб" or low == "лаб.":
        kind = "лаб"
    elif low in ("л",):
        kind = "Л"
    elif low in ("пр", "практ", "практ."):
        kind = "Пр"
    elif low in ("сем", "сем."):
        kind = "Сем"

    return subject, kind


def looks_like_teacher(text: str) -> bool:
    """
    Поддерживает:
      Півкач І. О.
      Красненко О. М.
      Чернишевич Олена Володимирівна
      Ковтун О. І.
    """
    text = clean_text(text)

    if not text or len(text) < 5:
        return False

    # Служебные значения
    low = text.lower()
    if any(
        x in low
        for x in (
            "zoom",
            "google",
            "meet",
            "http",
            "passcode",
            "код:",
            "id:",
            "підгр",
            "підгруп",
        )
    ):
        return False

    # Фамилия + инициалы
    if re.fullmatch(
        r"[А-ЯІЇЄҐ][а-яіїєґ'’\-]+\s+[А-ЯІЇЄҐ]\.\s*[А-ЯІЇЄҐ]\.?",
        text,
    ):
        return True

    # Фамилия + имя + отчество
    words = text.split()
    if 2 <= len(words) <= 4:
        cyr_words = [
            re.fullmatch(r"[А-ЯІЇЄҐ][а-яіїєґ'’\-]+", w)
            for w in words
        ]
        if all(cyr_words):
            return True

    return False


def looks_like_link(text: str) -> bool:
    text = clean_text(text).lower()

    return (
        text.startswith("http://")
        or text.startswith("https://")
        or "meet.google.com" in text
        or "zoom.us" in text
        or "knu-ua.zoom" in text
    )


def looks_like_subgroup_marker(text: str) -> bool:
    text = clean_text(text).lower()
    return (
        text.startswith("підгр")
        or text.startswith("підгруп")
    )


# ============================================================
# Главный Excel parser
# ============================================================

class MergedCellReader:
    """
    Быстрый доступ к значению merged-cell.

    Если ячейка находится внутри:
        C13:N15

    то для любой C13...N15 будет возвращено значение C13.
    """

    def __init__(self, ws):
        self.ws = ws
        self.cell_to_top_left = {}

        for merged in ws.merged_cells.ranges:
            top_left = (merged.min_row, merged.min_col)

            for row in range(merged.min_row, merged.max_row + 1):
                for col in range(merged.min_col, merged.max_col + 1):
                    self.cell_to_top_left[(row, col)] = top_left

    def value(self, row: int, col: int):
        top_left = self.cell_to_top_left.get((row, col))

        if top_left:
            r, c = top_left
            return self.ws.cell(r, c).value

        return self.ws.cell(row, col).value

    def top_left(self, row: int, col: int):
        return self.cell_to_top_left.get((row, col), (row, col))


def get_sheet_week(sheet_name: str):
    match = re.match(r"^\s*(1|2)\s+тиждень", sheet_name, re.I)
    if match:
        return int(match.group(1))
    return None


def build_slots(reader: MergedCellReader, ws):
    """
    Возвращает список колонок, которые действительно относятся
    к учебным группам.

    Структура исходной таблицы содержит много вспомогательных
    колонок с повторяющимися 'день/час'. Они здесь автоматически
    отбрасываются, потому что в строках 3-4 у них нет группы/
    подгруппы.
    """
    slots = []

    for col in range(3, ws.max_column + 1):
        group = clean_text(reader.value(3, col))
        subgroup = clean_text(reader.value(4, col))

        if not group and not subgroup:
            continue

        # row 3 может содержать переносы строк и дополнительный
        # текст типа "Вибірковий блок ...".
        # Извлекаем именно "група XXX".
        group_match = re.search(
            r"група\s+([^\n]+)",
            group,
            flags=re.IGNORECASE,
        )

        if group_match:
            group_name = "група " + group_match.group(1).strip()
        else:
            group_name = group

        # Иногда row 4 имеет обычную "підгрупа 1",
        # иногда специальное "підгрупа ІПЗм-21/1".
        subgroup = subgroup.strip()

        slots.append(
            {
                "col": col,
                "group": group_name,
                "subgroup": subgroup,
            }
        )

    return slots


def get_merged_range_for_top_left(ws, top_left):
    r, c = top_left

    for merged in ws.merged_cells.ranges:
        if merged.min_row == r and merged.min_col == c:
            return merged

    return None


def find_time_rows(reader: MergedCellReader, ws):
    """
    Время находится в колонке B и обычно объединено вертикально:
        B5:B12
        B13:B20
        ...
    Поэтому проверяем только B.
    """
    rows = []

    for row in range(5, ws.max_row + 1):
        value = reader.value(row, 2)

        if is_time(value):
            rows.append(row)

    return rows


def extract_metadata_for_slot(
    reader: MergedCellReader,
    ws,
    start_row: int,
    end_row: int,
    col: int,
    subject_top_left,
):
    """
    Ищет преподавателя, ссылку, аудиторию и примечания
    в блоке конкретной пары.
    """
    teacher = ""
    link = ""
    room = ""
    notes = []

    seen = set()

    for row in range(start_row + 1, end_row):
        value = clean_text(reader.value(row, col))

        if not value:
            continue

        # Значение самой пары не считаем metadata.
        if reader.top_left(row, col) == subject_top_left:
            continue

        key = value
        if key in seen:
            continue
        seen.add(key)

        if looks_like_subgroup_marker(value):
            continue

        # Дата вида [07.09]
        if re.fullmatch(r"\[\d{1,2}\.\d{1,2}\]", value):
            if value not in notes:
                notes.append(value)
            continue

        if looks_like_teacher(value):
            if not teacher:
                teacher = value
            continue

        if looks_like_link(value):
            # Иногда одна "ссылка" в исходнике выглядит просто
            # как "zoom" или "meet." без URL. Такие значения
            # тоже полезно сохранить.
            if not link:
                link = value
            continue

        # Числовая аудитория, например 56
        if re.fullmatch(r"\d+(?:\.0+)?", value):
            if not room:
                room = value.rstrip("0").rstrip(".")
            continue

        # Остальные текстовые значения считаем примечаниями.
        # Отбрасываем очевидный мусор.
        low = value.lower()
        if low not in {"zoom", "meet.", "knu-ua.zoom"}:
            notes.append(value)

    return {
        "Викладач": teacher,
        "Аудиторія": room,
        "Посилання": link,
        "Примітка": " | ".join(dict.fromkeys(notes)),
    }


def parse_sheet(ws) -> list[dict]:
    """
    Парсит один лист университета.
    """
    reader = MergedCellReader(ws)
    slots = build_slots(reader, ws)

    if not slots:
        logger.warning("На листе '%s' не найдены группы", ws.title)
        return []

    time_rows = find_time_rows(reader, ws)

    if not time_rows:
        logger.warning("На листе '%s' не найдены пары", ws.title)
        return []

    week = get_sheet_week(ws.title)

    records = []

    for i, start_row in enumerate(time_rows):
        next_time_row = (
            time_rows[i + 1]
            if i + 1 < len(time_rows)
            else ws.max_row + 1
        )

        time_value = clean_text(reader.value(start_row, 2))

        # День находится в A и тоже часто merged.
        day = normalize_day(reader.value(start_row, 1))

        if not day:
            # Иногда день не попал ровно в start_row.
            # Ищем ближайший сверху.
            for rr in range(start_row, max(1, start_row - 20), -1):
                candidate = normalize_day(reader.value(rr, 1))
                if candidate in DAY_MAP.values():
                    day = candidate
                    break

        # Находим все уникальные subject merged ranges,
        # которые начинаются именно с этой строки.
        subject_ranges = {}

        for slot in slots:
            col = slot["col"]
            value = clean_text(reader.value(start_row, col))

            if not value:
                continue

            # Пропускаем повторяющиеся служебные time/day.
            if is_time(value):
                continue

            low = value.lower()
            if low in DAY_MAP:
                continue

            top_left = reader.top_left(start_row, col)

            # Нам нужен range, начинающийся на start_row.
            # Если значение пришло из вертикального merge,
            # который начался раньше, это не новая пара.
            if top_left[0] != start_row:
                continue

            subject_ranges[top_left] = value

        for subject_top_left, raw_subject in subject_ranges.items():
            merged = get_merged_range_for_top_left(
                ws,
                subject_top_left,
            )

            if merged:
                min_col = merged.min_col
                max_col = merged.max_col
            else:
                min_col = max_col = subject_top_left[1]

            subject, kind = split_subject_and_kind(raw_subject)

            if not subject:
                continue

            # Какие группы/подгруппы покрывает merged subject.
            affected_slots = [
                slot
                for slot in slots
                if min_col <= slot["col"] <= max_col
            ]

            if not affected_slots:
                continue

            for slot in affected_slots:
                metadata = extract_metadata_for_slot(
                    reader=reader,
                    ws=ws,
                    start_row=start_row,
                    end_row=next_time_row,
                    col=slot["col"],
                    subject_top_left=subject_top_left,
                )

                records.append(
                    {
                        "Група": slot["group"],
                        "Підгрупа": slot["subgroup"],
                        "День": day,
                        "Час": time_value,
                        "Предмет": subject,
                        "Вид": kind,
                        "Викладач": metadata["Викладач"],
                        "Аудиторія": metadata["Аудиторія"],
                        "Посилання": metadata["Посилання"],
                        "Примітка": metadata["Примітка"],
                        "Тиждень": week,
                        "Лист": ws.title,
                    }
                )

    return records


def parse_xlsx(content: bytes) -> pd.DataFrame:
    """
    Парсит весь workbook, а не отдельный gid.
    """
    # data_only=True важен для VLOOKUP/других формул.
    # Google при XLSX export обычно сохраняет рассчитанное значение.
    workbook = openpyxl.load_workbook(
        io.BytesIO(content),
        data_only=True,
        read_only=False,
    )

    all_records = []

    for ws in workbook.worksheets:
        if ws.title.strip().lower() == "посилання":
            continue

        try:
            records = parse_sheet(ws)
            all_records.extend(records)

            logger.info(
                "Лист '%s': %d записей",
                ws.title,
                len(records),
            )
        except Exception:
            logger.exception(
                "Ошибка парсинга листа '%s'",
                ws.title,
            )

    columns = [
        "Група",
        "Підгрупа",
        "День",
        "Час",
        "Предмет",
        "Вид",
        "Викладач",
        "Аудиторія",
        "Посилання",
        "Примітка",
        "Тиждень",
        "Лист",
    ]

    df = pd.DataFrame(all_records, columns=columns)

    if df.empty:
        return df

    df = df.fillna("")

    # Чистим группы от случайных пробелов.
    df["Група"] = (
        df["Група"]
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    df["Підгрупа"] = (
        df["Підгрупа"]
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    # Если в config.GROUPS есть список конкретных групп,
    # оставляем только их.
    if GROUPS:
        # Поддержка и "ІПЗ-11", и "група ІПЗ-11"
        allowed = set()
        for g in GROUPS:
            g = clean_text(g)
            allowed.add(g)
            if g.startswith("група "):
                allowed.add(g.replace("група ", "").strip())
            else:
                allowed.add(f"група {g}")
        df = df[df["Група"].isin(allowed)]

    # Убираем полные дубли, которые могут появиться
    # из-за особенностей merged cells.
    df = df.drop_duplicates(
        subset=[
            "Група",
            "Підгрупа",
            "День",
            "Час",
            "Предмет",
            "Викладач",
            "Посилання",
        ]
    )

    day_order = {
        "Понеділок": 0,
        "Вівторок": 1,
        "Середа": 2,
        "Четвер": 3,
        "П'ятниця": 4,
        "Субота": 5,
    }

    df["_day_order"] = df["День"].map(day_order).fillna(99)
    df["_week_order"] = pd.to_numeric(
        df["Тиждень"],
        errors="coerce",
    ).fillna(99)

    df = (
        df.sort_values(
            by=[
                "Група",
                "_week_order",
                "_day_order",
                "Час",
                "Підгрупа",
            ]
        )
        .drop(columns=["_day_order", "_week_order"])
        .reset_index(drop=True)
    )

    logger.info(
        "Всего после парсинга: %d записей, %d групп",
        len(df),
        df["Група"].nunique(),
    )

    return df


# ============================================================
# Автоматическое определение текущей недели
# ============================================================

def current_university_week(today=None) -> int:
    """
    Для текущего workbook:
      01.09.2026 - 06.09.2026 = 1 тиждень
      07.09.2026 - 13.09.2026 = 2 тиждень
      дальше чередование 1/2.

    Если расписание университета позже поменяет дату начала,
    достаточно изменить ACADEMIC_START_DATE.
    """
    ACADEMIC_START_DATE = date(2026, 9, 1)

    if today is None:
        today = date.today()

    delta_days = (today - ACADEMIC_START_DATE).days

    if delta_days < 0:
        return 1

    # Недельный блок:
    # 0..6 -> 1
    # 7..13 -> 2
    # 14..20 -> 1
    return (delta_days // 7) % 2 + 1


# ============================================================
# Интерфейс, совместимый с текущим bot.py
# ============================================================

def fetch_and_parse_schedule(
    url: str | None = None,
    force: bool = False,
) -> pd.DataFrame:
    if url is None:
        url = bot_data.get(
            "schedule_url",
            DEFAULT_SCHEDULE_URL,
        )

    try:
        content = download_xlsx(url)
        df = parse_xlsx(content)

        if df.empty:
            logger.warning("После парсинга расписание пустое")

        return df

    except Exception as e:
        logger.exception("Ошибка загрузки/парсинга расписания: %s", e)
        return pd.DataFrame()


_schedule_cache = None
_cache_time = None


def get_schedule_df(
    force: bool = False,
    only_current_week: bool = True,
) -> pd.DataFrame:
    global _schedule_cache, _cache_time

    now = datetime.now()

    if (
        not force
        and _schedule_cache is not None
        and _cache_time
        and (now - _cache_time) < timedelta(minutes=30)
    ):
        df = _schedule_cache
    else:
        df = fetch_and_parse_schedule(force=force)
        _schedule_cache = df
        _cache_time = now

    if (
        only_current_week
        and not df.empty
        and "Тиждень" in df.columns
    ):
        week = current_university_week()

        df = df[
            pd.to_numeric(
                df["Тиждень"],
                errors="coerce",
            ) == week
        ].copy()

    return df


def get_schedule_for_group(
    group: str,
    subgroup: str | None = None,
    day: str | None = None,
) -> pd.DataFrame:
    df = get_schedule_df()

    if df.empty:
        return df

    # Поддержка и "ІПЗ-11", и "група ІПЗ-11"
    group = str(group).strip()
    candidates = {group}
    if group.startswith("група "):
        candidates.add(group.replace("група ", "").strip())
    else:
        candidates.add(f"група {group}")

    df = df[df["Група"].isin(candidates)].copy()

    if subgroup:
        subg = (
            df["Підгрупа"]
            .astype(str)
            .str.strip()
        )
        # Поддержка и "11", и "підгрупа 11"
        subg_num = subg.str.extract(r"(\d+)", expand=False).fillna("")
        # Общая пара без конкретной подгруппы показывается всем
        mask = (
            (subg == "")
            | (subg == "*")
            | (subg == str(subgroup))
            | (subg_num == str(subgroup))
        )
        df = df[mask]

    if day:
        df = df[df["День"] == day]

    day_order = {
        "Понеділок": 0,
        "Вівторок": 1,
        "Середа": 2,
        "Четвер": 3,
        "П'ятниця": 4,
        "Субота": 5,
    }

    df["_day_order"] = (
        df["День"]
        .map(day_order)
        .fillna(99)
    )

    df = (
        df.sort_values(
            by=[
                "_day_order",
                "Час",
                "Підгрупа",
            ]
        )
        .drop(columns=["_day_order"])
        .reset_index(drop=True)
    )

    return df


def format_schedule(
    df: pd.DataFrame,
    title: str = "",
) -> str:
    if df.empty:
        return (
            f"{title}\n\nНа цей день пар немає 🎉"
            if title
            else "На цей день пар немає 🎉"
        )

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
        subg = str(
            row.get("Підгрупа", "")
        ).strip()
        room = str(
            row.get("Аудиторія", "")
        ).strip()

        kind_emoji = (
            "📘"
            if kind == "Л"
            else "🔬"
            if "лаб" in str(kind).lower()
            else "📗"
            if kind == "Пр"
            else "📕"
        )

        line = (
            f"{kind_emoji} <b>{time}</b> — {subject}"
        )

        if kind:
            line += f" ({kind})"

        if subg and subg not in ("", "*"):
            line += f" [підгр. {subg}]"

        if room:
            line += f" 🏫 {room}"

        lines.append(line)

        if teacher:
            lines.append(f"   👤 {teacher}")

        if link and str(link).startswith("http"):
            # Экранируем одинарные кавычки для Telegram HTML.
            safe_link = str(link).replace("'", "&#39;")
            lines.append(
                f"   🔗 <a href='{safe_link}'>Посилання</a>"
            )
        elif link:
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

    df = get_schedule_df(
        force=True,
        only_current_week=False,
    )

    return not df.empty
