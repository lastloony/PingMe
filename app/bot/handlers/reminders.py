"""Хендлеры напоминаний с парсингом естественного языка"""
import re
from datetime import datetime

import dateparser
from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from app.bot.bot import dp
from app.database import Reminder
from app.database.base import AsyncSessionLocal
from app.services.scheduler import schedule_reminder


router = Router()

DATEPARSER_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "RETURN_AS_TIMEZONE_AWARE": False,
    "DATE_ORDER": "DMY",
}

# Паттерны явного времени в тексте (только HH:MM с двоеточием, не с точкой)
_EXPLICIT_TIME_RE = re.compile(
    r"\b\d{1,2}:\d{2}\b"
    r"|\b\d{1,2}\s*(?:утра|вечера|вечером|ночи|дня|днём)\b"
    r"|\bчерез\s+\d"
    r"|\b\d{1,2}\s*час[а-я]*\b",
    flags=re.IGNORECASE,
)

# Нормализация разговорного времени: «7 утра» → «07:00», «7 вечера» → «19:00»
_MORNING_RE = re.compile(r"\b(\d{1,2})\s*утра\b", flags=re.IGNORECASE)
_NIGHT_RE   = re.compile(r"\b(\d{1,2})\s*ночи\b", flags=re.IGNORECASE)
_EVENING_RE = re.compile(r"\b(\d{1,2})\s*(?:вечера|вечером)\b", flags=re.IGNORECASE)
_DAY_RE     = re.compile(r"\b(\d{1,2})\s*(?:дня|днём)\b", flags=re.IGNORECASE)
_HOUR_RE    = re.compile(r"\b(\d{1,2})\s*час(?:ов|а|ах)?\b", flags=re.IGNORECASE)

# Префикс «напомни [мне]» — убираем из текста напоминания
_PREFIX_RE  = re.compile(r"^напомни(?:те)?\s*(?:мне\s*)?", flags=re.IGNORECASE)

# Явные датовые паттерны: 19.02, 19.02.2026, 19/02
_DATE_NUMERIC_RE = re.compile(
    r"\b\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?\b"
)
# Относительные и именованные даты
_DATE_WORDS_RE = re.compile(
    r"\b(?:сегодня|завтра|послезавтра|через\s+\d+\s*(?:день|дня|дней|неделю|недели|недель)|"
    r"следующ(?:ий|ую|ее|ие)\s+\w+|"
    r"в\s+(?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)|"
    r"понедельник[а-я]*|вторник[а-я]*|среду?|среды|четверг[а-я]*|"
    r"пятниц[а-я]*|суббот[а-я]*|воскресень[а-я]*)\b",
    flags=re.IGNORECASE,
)
# Паттерны времени после нормализации
_TIME_RE = re.compile(
    r"\b\d{1,2}[:.]\d{2}\b"
    r"|\bчерез\s+\d+\s*(?:минут[а-я]*|час[а-я]*)\b",
    flags=re.IGNORECASE,
)


def _normalize_time(text: str) -> str:
    """Заменяет разговорные обозначения времени на числовой формат ЧЧ:00."""
    def morning(m: re.Match) -> str:
        return f"{int(m.group(1)):02d}:00"

    def evening(m: re.Match) -> str:
        return f"{(int(m.group(1)) + 12) % 24:02d}:00"

    text = _MORNING_RE.sub(morning, text)
    text = _NIGHT_RE.sub(morning, text)
    text = _EVENING_RE.sub(evening, text)
    text = _DAY_RE.sub(evening, text)
    text = _HOUR_RE.sub(morning, text)   # «13 часов» → «13:00»
    return text


# Только DD.MM без года — не трогаем DD.MM.YYYY
_SHORT_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?![./]\d)\b")


def _expand_short_dates(text: str) -> str:
    """Разворачивает «19.02» → «19.02.2026» чтобы dateparser не терялся."""
    year = datetime.now().year

    def expand(m: re.Match) -> str:
        return f"{m.group(1)}.{m.group(2)}.{year}"

    return _SHORT_DATE_RE.sub(expand, text)


def _shift_to_future(dt: datetime) -> datetime:
    """Если дата в прошлом — сдвигаем на год вперёд (парсер выбрал прошлый год)."""
    if dt <= datetime.now():
        dt = dt.replace(year=dt.year + 1)
    return dt


def _extract_datetime_fragments(text: str) -> list[str]:
    """Собирает все датовые/временны́е фрагменты из текста без дублей."""
    seen: set[str] = set()
    fragments: list[str] = []
    for pattern in (_DATE_NUMERIC_RE, _DATE_WORDS_RE, _TIME_RE):
        for m in pattern.finditer(text):
            val = m.group()
            if val not in seen:
                seen.add(val)
                fragments.append(val)

    # Убираем фрагменты, которые являются подстрокой другого фрагмента
    # (например «20.02» внутри «20.02.2026»)
    return [f for f in fragments if not any(f != g and f in g for g in fragments)]


def _parse_reminder(raw: str) -> tuple[str, datetime] | None:
    """
    Извлекает (текст напоминания, дату) из произвольной строки.
    Возвращает None если дату распознать не удалось.
    """
    text = _normalize_time(_PREFIX_RE.sub("", raw.strip()))

    # Шаг 1: находим датовые/временны́е фрагменты регулярками
    fragments = _extract_datetime_fragments(text)
    if not fragments:
        return None

    # Шаг 2: парсим только фрагменты, без лишних слов
    date_str = _expand_short_dates(" ".join(fragments))
    dt = dateparser.parse(date_str, languages=["ru"], settings=DATEPARSER_SETTINGS)
    if dt is None:
        return None
    dt = _shift_to_future(dt)

    # Шаг 3: вырезаем все фрагменты из текста — остаток и есть напоминание
    reminder_text = text
    for fragment in fragments:
        reminder_text = reminder_text.replace(fragment, "")
    # Убираем хвосты вроде «20.» или «в »
    reminder_text = re.sub(r"\b\d{1,2}[./]", "", reminder_text)
    reminder_text = re.sub(r"\s{2,}", " ", reminder_text).strip()
    reminder_text = re.sub(r"^[\s,\-–—]+|[\s,\-–—]+$", "", reminder_text)
    reminder_text = re.sub(r"\s+в$", "", reminder_text)  # одиночное «в» в конце
    reminder_text = re.sub(r"^в\s+", "", reminder_text)  # одиночное «в» в начале

    if not reminder_text:
        reminder_text = raw.strip()

    return reminder_text, dt


def _has_explicit_time(text: str) -> bool:
    return bool(_EXPLICIT_TIME_RE.search(text))


class HasDateFilter(BaseFilter):
    """Пропускает сообщение только если в тексте найдена дата/время."""
    async def __call__(self, message: Message) -> bool:
        return bool(message.text) and _parse_reminder(message.text) is not None


class ReminderStates(StatesGroup):
    waiting_for_time = State()


@router.message(StateFilter(None), F.text, HasDateFilter())
async def remind_from_text(message: Message, state: FSMContext):
    """Создаёт напоминание из произвольной фразы."""
    await _handle_reminder_text(message, message.text, state)


async def _handle_reminder_text(message: Message, raw: str, state: FSMContext):
    parsed = _parse_reminder(raw)

    if parsed is None:
        await message.answer(
            "❌ Не смог распознать дату или время.\n\n"
            "Формат: <b>текст дата время</b>\n"
            "• <i>позвонить маме завтра в 10:00</i>\n"
            "• <i>подъем 17.02 в 5 утра</i>\n"
            "• <i>встреча в пятницу в 15:00</i>"
        )
        return

    reminder_text, remind_at = parsed

    # Время не указано явно — спрашиваем
    if not _has_explicit_time(raw):
        await state.set_state(ReminderStates.waiting_for_time)
        await state.update_data(
            reminder_text=reminder_text,
            remind_date=remind_at.strftime("%d.%m.%Y"),
        )
        await message.answer(
            f"📅 Дата: <b>{remind_at.strftime('%d.%m.%Y')}</b>\n"
            f"📝 Текст: <b>{reminder_text}</b>\n\n"
            "В какое время напомнить?\n"
            "Например: <i>10:00</i>, <i>9 утра</i>, <i>7 вечера</i>"
        )
        return

    if remind_at <= datetime.now():
        await message.answer(
            "❌ Время напоминания уже в прошлом.\n"
            "Укажи время в будущем."
        )
        return

    await _save_reminder(message, reminder_text, remind_at, state)


@router.message(ReminderStates.waiting_for_time, F.text)
async def handle_time_input(message: Message, state: FSMContext):
    """Получает время от пользователя и завершает создание напоминания."""
    data = await state.get_data()
    time_str = _normalize_time(message.text.strip())
    dt = dateparser.parse(
        f"{data['remind_date']} {time_str}",
        languages=["ru"],
        settings=DATEPARSER_SETTINGS,
    )

    if dt is None:
        await message.answer(
            "❌ Не смог распознать время. Попробуй ещё раз.\n"
            "Например: <i>10:00</i>, <i>9 утра</i>, <i>7 вечера</i>"
        )
        return

    if dt <= datetime.now():
        await message.answer("❌ Это время уже в прошлом. Укажи время в будущем.")
        return

    await _save_reminder(message, data["reminder_text"], dt, state)


async def _save_reminder(message: Message, reminder_text: str, remind_at: datetime, state: FSMContext):
    async with AsyncSessionLocal() as session:
        reminder = Reminder(
            user_id=message.from_user.id,
            text=reminder_text,
            remind_at=remind_at,
        )
        session.add(reminder)
        await session.commit()
        await session.refresh(reminder)
        schedule_reminder(reminder)

    await state.clear()
    await message.answer(
        f"✅ Напоминание создано!\n\n"
        f"📝 {reminder_text}\n"
        f"⏰ {remind_at.strftime('%d.%m.%Y %H:%M')}"
    )


@router.message(Command("list"))
async def cmd_list(message: Message):
    async with AsyncSessionLocal() as session:
        query = (
            select(Reminder)
            .where(
                Reminder.user_id == message.from_user.id,
                Reminder.is_active == True,
                Reminder.is_sent == False,
            )
            .order_by(Reminder.remind_at)
        )
        result = await session.execute(query)
        reminders = result.scalars().all()

    if not reminders:
        await message.answer("📭 У тебя пока нет активных напоминаний.")
        return

    lines = ["📋 <b>Твои напоминания:</b>\n"]
    for i, r in enumerate(reminders, 1):
        lines.append(
            f"{i}. <code>ID {r.id}</code> — {r.remind_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"   📝 {r.text}"
        )
    lines.append("\nДля удаления: /delete &lt;ID&gt;")
    await message.answer("\n".join(lines))


@router.message(Command("delete"))
async def cmd_delete(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Укажи ID напоминания. Например: /delete 1")
        return

    try:
        reminder_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный ID напоминания.")
        return

    async with AsyncSessionLocal() as session:
        query = select(Reminder).where(
            Reminder.id == reminder_id,
            Reminder.user_id == message.from_user.id,
        )
        result = await session.execute(query)
        reminder = result.scalar_one_or_none()

        if not reminder:
            await message.answer("❌ Напоминание не найдено.")
            return

        reminder.is_active = False
        await session.commit()

    await message.answer("✅ Напоминание удалено.")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await state.get_state() is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("✅ Действие отменено.")


dp.include_router(router)