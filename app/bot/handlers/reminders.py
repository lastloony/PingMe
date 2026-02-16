"""Хендлеры напоминаний с парсингом естественного языка"""
import re
from datetime import datetime, timedelta

import dateparser
import pytz
from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from app.bot.bot import dp
from app.config import settings
from app.database import Reminder
from app.database.base import AsyncSessionLocal
from app.services.scheduler import schedule_reminder, scheduler

router = Router()

_TZ = pytz.timezone(settings.timezone)


def _now() -> datetime:
    """Текущее время в московском часовом поясе (наивный datetime для хранения в БД)."""
    return datetime.now(_TZ).replace(tzinfo=None)


DATEPARSER_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "RETURN_AS_TIMEZONE_AWARE": False,
    "DATE_ORDER": "DMY",
    "TIMEZONE": settings.timezone,
    "TO_TIMEZONE": settings.timezone,
}

# Паттерны явного времени в тексте (только HH:MM с двоеточием, не с точкой)
_EXPLICIT_TIME_RE = re.compile(
    r"\b\d{1,2}[:-]\d{2}\b"
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
    r"|\b\d{1,2}-\d{2}\b"
    r"|\bчерез\s+\d+\s*(?:минут[а-я]*|час[а-я]*)\b",
    flags=re.IGNORECASE,
)


_DASH_TIME_RE = re.compile(r"\b(\d{1,2})-(\d{2})\b")


def _normalize_time(text: str) -> str:
    """Заменяет разговорные обозначения времени на числовой формат ЧЧ:00."""
    def morning(m: re.Match) -> str:
        return f"{int(m.group(1)):02d}:00"

    def evening(m: re.Match) -> str:
        return f"{(int(m.group(1)) + 12) % 24:02d}:00"

    def dash_time(m: re.Match) -> str:
        return f"{m.group(1)}:{m.group(2)}"

    text = _DASH_TIME_RE.sub(dash_time, text)  # «10-00» → «10:00»
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
    year = _now().year

    def expand(m: re.Match) -> str:
        return f"{m.group(1)}.{m.group(2)}.{year}"

    return _SHORT_DATE_RE.sub(expand, text)


def _shift_to_future(dt: datetime) -> datetime:
    """Если дата в прошлом — сдвигаем на год вперёд (парсер выбрал прошлый год)."""
    if dt <= _now():
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
    reminder_text = re.sub(r"\s+в$", "", reminder_text, flags=re.IGNORECASE)  # одиночное «в» в конце
    reminder_text = re.sub(r"^в\s+", "", reminder_text, flags=re.IGNORECASE)  # одиночное «в» в начале

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
    waiting_for_delete_id = State()


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

    if remind_at <= _now():
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

    if dt <= _now():
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
                Reminder.is_confirmed == False,
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
        status = "⏱ Отложено" if r.message_id else "⏰"
        lines.append(
            f"{i}. <code>ID {r.id}</code> {status} — {r.remind_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"   📝 {r.text}"
        )
    lines.append("\nДля удаления: /delete &lt;ID&gt;")
    await message.answer("\n".join(lines))


@router.message(Command("delete"))
async def cmd_delete(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) < 2:
        async with AsyncSessionLocal() as session:
            query = (
                select(Reminder)
                .where(
                    Reminder.user_id == message.from_user.id,
                    Reminder.is_active == True,
                    Reminder.is_confirmed == False,
                )
                .order_by(Reminder.remind_at)
            )
            result = await session.execute(query)
            reminders = result.scalars().all()

        if not reminders:
            await message.answer("📭 У тебя нет активных напоминаний.")
            return

        lines = ["🗑 <b>Какое напоминание удалить?</b>\n"]
        for r in reminders:
            lines.append(
                f"<code>{r.id}</code> — {r.remind_at.strftime('%d.%m.%Y %H:%M')} — {r.text}"
            )
        lines.append("\nВведи ID напоминания или /cancel для отмены:")
        await state.set_state(ReminderStates.waiting_for_delete_id)
        await message.answer("\n".join(lines))
        return

    await _do_delete(message, parts[1], state)


@router.message(ReminderStates.waiting_for_delete_id, F.text)
async def handle_delete_id_input(message: Message, state: FSMContext):
    await _do_delete(message, message.text.strip(), state)


async def _do_delete(message: Message, raw_id: str, state: FSMContext):
    try:
        reminder_id = int(raw_id)
    except ValueError:
        await message.answer("❌ Неверный ID. Введи число.")
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
            await state.clear()
            return

        reminder.is_active = False
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Напоминание удалено.\n\n"
        f"🆔 {reminder.id} — {reminder.remind_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 {reminder.text}"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await state.get_state() is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("✅ Действие отменено.")


def _cancel_reminder_job(reminder_id: int):
    job_id = f"reminder_{reminder_id}"
    job = scheduler.get_job(job_id)
    if job:
        job.remove()


@router.callback_query(F.data.regexp(r"^rem:(done|snooze):(\d+)$"))
async def handle_reminder_callback(callback: CallbackQuery):
    match = re.match(r"^rem:(done|snooze):(\d+)$", callback.data)
    action = match.group(1)
    reminder_id = int(match.group(2))

    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or reminder.user_id != callback.from_user.id:
            await callback.answer("Напоминание не найдено.", show_alert=True)
            return

        if action == "done":
            reminder.is_confirmed = True
            reminder.is_active = False
            await session.commit()
            _cancel_reminder_job(reminder_id)
            await callback.message.edit_text(
                f"⏰ <b>Напоминание!</b>\n\n{reminder.text}\n\n✅ <i>Выполнено</i>"
            )

        elif action == "snooze":
            reminder.remind_at = _now() + timedelta(hours=1)
            reminder.is_confirmed = False
            reminder.message_id = None
            await session.commit()
            _cancel_reminder_job(reminder_id)
            # Планируем через 1 час
            from apscheduler.triggers.date import DateTrigger
            from app.services.scheduler import send_reminder
            scheduler.add_job(
                send_reminder,
                trigger=DateTrigger(timezone=_TZ, run_date=reminder.remind_at),
                args=[reminder_id],
                id=f"reminder_{reminder_id}",
                replace_existing=True,
                misfire_grace_time=60,
            )
            await callback.message.edit_text(
                f"⏰ <b>Напоминание!</b>\n\n{reminder.text}\n\n⏱ <i>Отложено на 1 час</i>"
            )

    await callback.answer()


dp.include_router(router)