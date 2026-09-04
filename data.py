import pandas as pd
from pathlib import Path
from config import SCHEDULE_FILE, GROUPS

# Загружаем расписание один раз при старте
def load_schedule() -> pd.DataFrame:
    path = Path(__file__).parent / SCHEDULE_FILE
    if not path.exists():
        # fallback на артефакты
        path = Path("/home/workdir/artifacts") / SCHEDULE_FILE
    df = pd.read_csv(path, dtype=str).fillna("")
    return df

SCHEDULE_DF = load_schedule()


def get_schedule_for_group(group: str, day: str | None = None) -> pd.DataFrame:
    """Возвращает расписание группы, опционально фильтрует по дню"""
    df = SCHEDULE_DF[SCHEDULE_DF["Група"] == group].copy()
    if day:
        df = df[df["День"] == day]
    # Сортируем по времени
    df = df.sort_values(by="Час")
    return df


def format_schedule(df: pd.DataFrame, title: str = "") -> str:
    """Красиво форматирует расписание в текст"""
    if df.empty:
        return f"{title}\n\nНа цей день пар немає 🎉"

    lines = []
    if title:
        lines.append(f"<b>{title}</b>\n")

    current_day = None
    for _, row in df.iterrows():
        day = row["День"]
        if day != current_day:
            if current_day is not None:
                lines.append("")  # пустая строка между днями
            lines.append(f"📅 <b>{day}</b>")
            current_day = day

        time = row["Час"]
        subject = row["Предмет"]
        kind = row["Вид"]
        teacher = row["Викладач"]
        link = row["Посилання"]
        room = row["Аудиторія"]
        note = row["Примітка"]

        kind_emoji = "📘" if kind == "Л" else "📗" if kind == "Пр" else "📕"
        line = f"{kind_emoji} <b>{time}</b> — {subject}"
        if kind:
            line += f" ({kind})"
        lines.append(line)

        if teacher:
            lines.append(f"   👤 {teacher}")
        if room:
            lines.append(f"   🚪 {room}")
        if link:
            lines.append(f"   🔗 <a href='{link}'>Посилання на пару</a>")
        if note:
            lines.append(f"   📌 {note}")

    return "\n".join(lines)
