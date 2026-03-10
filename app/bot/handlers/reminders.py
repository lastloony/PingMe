"""Хендлеры напоминаний с парсингом естественного языка"""
import re
from datetime import datetime, timedelta

import dateparser
import pytz
from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from sqlalchemy import select

from apscheduler.triggers.date import DateTrigger

from app.bot.bot import dp
from app.config import settings
from app.database import Reminder, UserSettings
from app.database.base import AsyncSessionLocal
from app.services.scheduler import _next_occurrence, schedule_reminder, scheduler, send_reminder

router = Router()

_TZ = pytz.timezone(settings.timezone)


def _now() -> datetime:
    """Текущее время в московском часовом поясе (наивный datetime для хранения в БД)."""
    return datetime.now(_TZ).replace(tzinfo=None)


def _now_tz(tz: pytz.BaseTzInfo) -> datetime:
    """Текущее время в указанном часовом поясе (наивный datetime)."""
    return datetime.now(tz).replace(tzinfo=None)


# Дефолтные настройки dateparser (Москва) — используются только в HasDateFilter
DATEPARSER_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "RETURN_AS_TIMEZONE_AWARE": False,
    "DATE_ORDER": "DMY",
    "TIMEZONE": settings.timezone,
    "TO_TIMEZONE": settings.timezone,
}


def _dateparser_settings(tz_name: str) -> dict:
    """Настройки dateparser для конкретной таймзоны пользователя."""
    return {
        "PREFER_DATES_FROM": "future",
        "RETURN_AS_TIMEZONE_AWARE": False,
        "DATE_ORDER": "DMY",
        "TIMEZONE": tz_name,
        "TO_TIMEZONE": tz_name,
    }


# Паттерны явного времени в тексте
_EXPLICIT_TIME_RE = re.compile(
    r"\b\d{1,2}[:-]\d{2}\b"
    r"|\b\d{1,2}\.(?:00|[2-9]\d|1[3-9])\b"   # N.00, N.13–N.99 — безопасный точечный формат
    r"|\b\d{1,2}\s*(?:утра|вечера|вечером|ночи|дня|днём)\b"
    r"|\bчерез\s+\d"
    r"|\b\d{1,2}\s*час[а-я]*\b"
    r"|\bв\s+\d{1,2}\b",
    flags=re.IGNORECASE,
)

# Нормализация разговорного времени: «7 утра» → «07:00», «7 вечера» → «19:00»
_MORNING_RE = re.compile(r"\b(\d{1,2})\s*утра\b", flags=re.IGNORECASE)
_NIGHT_RE   = re.compile(r"\b(\d{1,2})\s*ночи\b", flags=re.IGNORECASE)
_EVENING_RE = re.compile(r"\b(\d{1,2})\s*(?:вечера|вечером)\b", flags=re.IGNORECASE)
_DAY_RE     = re.compile(r"\b(\d{1,2})\s*(?:дня|днём)\b", flags=re.IGNORECASE)
_HOUR_RE    = re.compile(r"(?<!через )\b(\d{1,2})\s*час(?:ов|а|ах)?\b", flags=re.IGNORECASE)

# Префикс «напомни [мне]» — убираем из текста напоминания
_PREFIX_RE  = re.compile(r"^напомни(?:те|ть)?\s*(?:мне\s*)?", flags=re.IGNORECASE)

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


# N.00, N.13-N.99 — безопасная конвертация точечного формата в двоеточие
_SAFE_DOT_TIME_RE = re.compile(r"\b(\d{1,2})\.(00|[2-9]\d|1[3-9])\b")
# N.01-N.12 — неоднозначно (может быть датой DD.MM)
_AMBIG_DOT_RE = re.compile(r"\b(\d{1,2})\.(0[1-9]|1[0-2])\b(?![./]\d)")

_DASH_TIME_RE = re.compile(r"\b(\d{1,2})-(\d{2})\b")
_IN_HOUR_RE   = re.compile(
    r"\bв\s+(\d{1,2})\b(?!\s*(?:утра|вечера|вечером|ночи|дня|днём|час[а-я]*|[-:.]\d))",
    flags=re.IGNORECASE,
)


_RECURRENCE_PATTERNS: dict[str, list[str]] = {
    "yearly":   [r"ежегодно", r"каждый\s+год", r"раз\s+в\s+год", r"каждое\s+\d+\s+\w+"],
    "monthly":  [r"ежемесячно", r"каждый\s+месяц", r"раз\s+в\s+месяц", r"каждое\s+\d+[- ]?числа?"],
    "weekly":   [r"еженедельно", r"каждую\s+неделю", r"раз\s+в\s+неделю", r"каждые\s+7\s+дней"],
    "weekdays": [r"по\s+будням", r"в\s+будни(?:е\s+дни)?", r"каждый\s+будний\s+день", r"только\s+в\s+будни"],
    "weekends": [r"по\s+выходным", r"в\s+выходные(?:\s+дни)?", r"каждые\s+выходные", r"только\s+в\s+выходные"],
    "daily":    [r"ежедневно", r"каждый\s+день", r"раз\s+в\s+день", r"каждые\s+сутки", r"раз\s+в\s+сутки"],
    "hourly":   [r"ежечасно", r"каждый\s+час", r"раз\s+в\s+час", r"каждые\s+60\s+минут"],
}

_RECURRENCE_LABELS = {
    "hourly":   "ежечасно",
    "daily":    "ежедневно",
    "weekly":   "еженедельно",
    "monthly":  "ежемесячно",
    "yearly":   "ежегодно",
    "weekdays": "по будням (пн–пт)",
    "weekends": "по выходным (сб–вс)",
}

_RECURRENCE_SHORT = {
    "hourly": "🔁ч", "daily": "🔁д", "weekly": "🔁н", "monthly": "🔁м", "yearly": "🔁г",
    "weekdays": "🔁пн-пт", "weekends": "🔁сб-вс",
}

_RECURRENCE_EXAMPLE_KW = {
    "hourly":   "каждый час",
    "daily":    "каждый день",
    "weekly":   "каждую неделю",
    "monthly":  "каждый месяц",
    "yearly":   "каждый год",
    "weekdays": "по будням",
    "weekends": "по выходным",
}


def _adjust_to_day_filter(dt: datetime, recurrence: str) -> datetime:
    """Сдвигает datetime на ближайший подходящий день для weekdays/weekends."""
    if recurrence == "weekdays":
        while dt.weekday() > 4:  # 5=сб, 6=вс
            dt += timedelta(days=1)
    elif recurrence == "weekends":
        while dt.weekday() < 5:  # 0=пн … 4=пт
            dt += timedelta(days=1)
    return dt


def _extract_recurrence(raw: str) -> tuple[str, str | None]:
    """Извлекает ключевое слово периодичности, возвращает (очищенный текст, recurrence | None)."""
    for recurrence, patterns in _RECURRENCE_PATTERNS.items():
        for pat in patterns:
            m = re.search(pat, raw, re.IGNORECASE)
            if m:
                cleaned = raw[:m.start()] + raw[m.end():]
                cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,–—")
                return cleaned, recurrence
    return raw, None


def _normalize_time(text: str) -> str:
    """Заменяет разговорные обозначения времени на числовой формат ЧЧ:00."""
    def morning(m: re.Match) -> str:
        return f"{int(m.group(1)):02d}:00"

    def evening(m: re.Match) -> str:
        return f"{(int(m.group(1)) + 12) % 24:02d}:00"

    def dash_time(m: re.Match) -> str:
        return f"{m.group(1)}:{m.group(2)}"

    text = _IN_HOUR_RE.sub(lambda m: f"в {int(m.group(1)):02d}:00", text)
    text = _DASH_TIME_RE.sub(dash_time, text)
    text = _MORNING_RE.sub(morning, text)
    text = _NIGHT_RE.sub(morning, text)
    text = _EVENING_RE.sub(evening, text)
    text = _DAY_RE.sub(evening, text)
    text = _HOUR_RE.sub(morning, text)
    text = _SAFE_DOT_TIME_RE.sub(lambda m: f"{m.group(1)}:{m.group(2)}", text)
    return text


# Только DD.MM без года — не трогаем DD.MM.YYYY
_SHORT_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?![./]\d)\b")


def _expand_short_dates(text: str, year: int | None = None) -> str:
    """Разворачивает «19.02» → «19.02.2026» чтобы dateparser не терялся."""
    if year is None:
        year = _now().year

    def expand(m: re.Match) -> str:
        return f"{m.group(1)}.{m.group(2)}.{year}"

    return _SHORT_DATE_RE.sub(expand, text)


def _find_dot_ambiguity(text: str) -> tuple[str, int, int] | None:
    """
    Ищет N.MM где 1 <= MM <= 12 и N <= 23 — может быть и временем и датой.
    Если рядом уже есть другое явное время — это дата, не спрашиваем.
    Возвращает (фрагмент, часы, минуты) или None.
    """
    m = _AMBIG_DOT_RE.search(text)
    if not m:
        return None
    h, mn = int(m.group(1)), int(m.group(2))
    if h > 23:
        return None  # не может быть временем → это дата
    rest = text[: m.start()] + text[m.end() :]
    if _has_explicit_time(rest):
        return None  # рядом уже есть явное время → этот фрагмент скорее дата
    return m.group(), h, mn


def _shift_to_future(dt: datetime, now: datetime | None = None) -> datetime:
    """Если дата в прошлом — сдвигаем на год вперёд (парсер выбрал прошлый год)."""
    if now is None:
        now = _now()
    if dt <= now:
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

    return [f for f in fragments if not any(f != g and f in g for g in fragments)]


def _parse_reminder(
    raw: str,
    dp_settings: dict | None = None,
    now: datetime | None = None,
) -> tuple[str, datetime] | None:
    """
    Извлекает (текст напоминания, дату) из произвольной строки.
    Возвращает None если дату распознать не удалось.
    """
    if dp_settings is None:
        dp_settings = DATEPARSER_SETTINGS
    if now is None:
        now = _now()

    text = _normalize_time(_PREFIX_RE.sub("", raw.strip()))

    fragments = _extract_datetime_fragments(text)
    if not fragments:
        return None

    date_str = _expand_short_dates(" ".join(fragments), year=now.year)
    dt = dateparser.parse(date_str, languages=["ru"], settings=dp_settings)
    if dt is None:
        return None
    dt = _shift_to_future(dt, now=now)

    reminder_text = text
    for fragment in fragments:
        reminder_text = reminder_text.replace(fragment, "")
    reminder_text = re.sub(r"\b\d{1,2}[./]", "", reminder_text)
    reminder_text = re.sub(r"\s{2,}", " ", reminder_text).strip()
    reminder_text = re.sub(r"^[\s,\-–—]+|[\s,\-–—]+$", "", reminder_text)
    reminder_text = re.sub(r"\s+в$", "", reminder_text, flags=re.IGNORECASE)
    reminder_text = re.sub(r"^в\s+", "", reminder_text, flags=re.IGNORECASE)

    if not reminder_text:
        reminder_text = raw.strip()

    return reminder_text, dt


def _has_explicit_time(text: str) -> bool:
    return bool(_EXPLICIT_TIME_RE.search(text))


async def _load_user_tz(user_id: int) -> pytz.BaseTzInfo:
    """Загружает часовой пояс пользователя из настроек (дефолт — Europe/Moscow)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        us = result.scalar_one_or_none()
    return pytz.timezone(us.timezone if us else settings.timezone)


class HasDateFilter(BaseFilter):
    """Пропускает сообщение если найдена дата/время или ключевое слово периодичности."""
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        _, recurrence = _extract_recurrence(message.text)
        if recurrence:
            return True
        return _parse_reminder(message.text) is not None


class ReminderStates(StatesGroup):
    waiting_for_time = State()
    waiting_for_delete_id = State()
    waiting_for_reschedule = State()
    waiting_for_dot_clarification = State()
    waiting_for_edit_text = State()
    waiting_for_edit_time = State()


@router.message(StateFilter(None), F.text, HasDateFilter())
async def remind_from_text(message: Message, state: FSMContext):
    """Создаёт напоминание из произвольной фразы."""
    await _handle_reminder_text(message, message.text, state)


async def _handle_reminder_text(
    message: Message, raw: str, state: FSMContext, user_id: int | None = None,
    recurrence: str | None = None,
):
    uid = user_id if user_id is not None else message.from_user.id

    if recurrence is None:
        raw, recurrence = _extract_recurrence(raw)

    # Проверяем неоднозначный точечный формат (18.02 — время или дата?)
    ambiguity = _find_dot_ambiguity(_PREFIX_RE.sub("", raw.strip()))
    if ambiguity:
        fragment, h, mn = ambiguity
        _MONTHS_RU = ["янв", "фев", "мар", "апр", "мая", "июн",
                      "июл", "авг", "сен", "окт", "ноя", "дек"]
        day = fragment.split(".")[0]
        month_name = _MONTHS_RU[mn - 1]
        await state.set_state(ReminderStates.waiting_for_dot_clarification)
        await state.update_data(
            raw_text=raw, fragment=fragment, h=h, mn=mn, user_id=uid, recurrence=recurrence,
        )
        await message.answer(
            f"❓ <b>{fragment}</b> — это время или дата?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=f"🕐 Время {h:02d}:{mn:02d}", callback_data="clarify:time"
                ),
                InlineKeyboardButton(
                    text=f"📅 Дата {day} {month_name}", callback_data="clarify:date"
                ),
            ]]),
        )
        return

    user_tz = await _load_user_tz(uid)
    now = _now_tz(user_tz)
    dp_s = _dateparser_settings(user_tz.zone)
    parsed = _parse_reminder(raw, dp_settings=dp_s, now=now)

    if parsed is None:
        if recurrence:
            label = _RECURRENCE_LABELS[recurrence]
            kw = _RECURRENCE_EXAMPLE_KW[recurrence]
            hint = raw.strip() or "текст"
            await message.answer(
                f"🔁 Повторяемость распознана: <b>{label}</b>\n\n"
                f"❌ Не указано начальное время.\n\n"
                f"Добавь когда начать, например:\n"
                f"• <i>{hint} завтра в 10:00 {kw}</i>\n"
                f"• <i>{hint} в 8 утра {kw}</i>"
            )
        else:
            await message.answer(
                "❌ Не смог распознать дату или время.\n\n"
                "Формат: <b>текст дата время</b>\n"
                "• <i>позвонить маме завтра в 10:00</i>\n"
                "• <i>подъем 17.02 в 5 утра</i>\n"
                "• <i>встреча в пятницу в 15:00</i>"
            )
        return

    reminder_text, remind_at = parsed

    if not _has_explicit_time(raw):
        await state.set_state(ReminderStates.waiting_for_time)
        await state.update_data(
            reminder_text=reminder_text,
            remind_date=remind_at.strftime("%d.%m.%Y"),
            tz_name=user_tz.zone,
            recurrence=recurrence,
        )
        await message.answer(
            f"📅 Дата: <b>{remind_at.strftime('%d.%m.%Y')}</b>\n"
            f"📝 Текст: <b>{reminder_text}</b>\n\n"
            "В какое время напомнить?\n"
            "Например: <i>10:00</i>, <i>9 утра</i>, <i>7 вечера</i>"
        )
        return

    if remind_at <= now:
        await message.answer(
            "❌ Время напоминания уже в прошлом.\n"
            "Укажи время в будущем."
        )
        return

    await _save_reminder(message, uid, reminder_text, remind_at, state, user_tz, recurrence=recurrence)


@router.message(ReminderStates.waiting_for_time, F.text, ~F.text.startswith("/"))
async def handle_time_input(message: Message, state: FSMContext):
    """Получает время от пользователя и завершает создание напоминания."""
    data = await state.get_data()
    tz_name = data.get("tz_name", settings.timezone)
    user_tz = pytz.timezone(tz_name)
    dp_s = _dateparser_settings(tz_name)

    time_str = _normalize_time(message.text.strip())
    dt = dateparser.parse(
        f"{data['remind_date']} {time_str}",
        languages=["ru"],
        settings=dp_s,
    )

    if dt is None:
        await message.answer(
            "❌ Не смог распознать время. Попробуй ещё раз.\n"
            "Например: <i>10:00</i>, <i>9 утра</i>, <i>7 вечера</i>"
        )
        return

    if dt <= _now_tz(user_tz):
        await message.answer("❌ Это время уже в прошлом. Укажи время в будущем.")
        return

    recurrence = data.get("recurrence")
    await _save_reminder(
        message, message.from_user.id, data["reminder_text"], dt, state, user_tz,
        recurrence=recurrence,
    )


@router.callback_query(
    StateFilter(ReminderStates.waiting_for_dot_clarification),
    F.data.in_({"clarify:time", "clarify:date"}),
)
async def handle_dot_clarification(callback: CallbackQuery, state: FSMContext):
    """Пользователь уточнил: NN.MM — это время или дата."""
    data = await state.get_data()
    raw: str = data["raw_text"]
    fragment: str = data["fragment"]
    h: int = data["h"]
    mn: int = data["mn"]
    uid: int = data.get("user_id", callback.from_user.id)

    recurrence = data.get("recurrence")
    await state.clear()

    if callback.data == "clarify:time":
        new_raw = raw.replace(fragment, f"{h:02d}:{mn:02d}", 1)
    else:
        new_raw = raw  # оставляем как дату

    await callback.answer()
    await _handle_reminder_text(callback.message, new_raw, state, user_id=uid, recurrence=recurrence)


async def _save_reminder(
    message: Message,
    user_id: int,
    reminder_text: str,
    remind_at: datetime,
    state: FSMContext,
    user_tz: pytz.BaseTzInfo,
    recurrence: str | None = None,
):
    if recurrence in ("weekdays", "weekends"):
        remind_at = _adjust_to_day_filter(remind_at, recurrence)

    async with AsyncSessionLocal() as session:
        reminder = Reminder(
            user_id=user_id,
            text=reminder_text,
            remind_at=remind_at,
            recurrence=recurrence,
            recurrence_anchor=remind_at if recurrence else None,
        )
        session.add(reminder)
        await session.commit()
        await session.refresh(reminder)
        schedule_reminder(reminder, tz=user_tz)

    await state.clear()
    rec_line = f"\n🔁 Повторяется: {_RECURRENCE_LABELS[recurrence]}" if recurrence else ""
    await message.answer(
        f"✅ Напоминание создано!\n\n"
        f"📝 {reminder_text}\n"
        f"⏰ {remind_at.strftime('%d.%m.%Y %H:%M')}"
        f"{rec_line}"
    )


async def _fetch_reminders(user_id: int) -> list:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Reminder)
            .where(
                Reminder.user_id == user_id,
                Reminder.is_active == True,
                Reminder.is_confirmed == False,
            )
            .order_by(Reminder.remind_at)
        )
        return result.scalars().all()


def _build_table(reminders) -> str:
    COL_TEXT = 22
    header = f"{'Дата':<11} {'Время':<6} {'Текст'}"
    sep = "─" * (11 + 1 + 6 + 1 + COL_TEXT)
    rows = [header, sep]
    for r in reminders:
        text = r.text[:COL_TEXT] + "…" if len(r.text) > COL_TEXT else r.text
        flag = " ⏱" if r.is_snoozed else ""
        rec_flag = f" {_RECURRENCE_SHORT.get(r.recurrence, '')}" if r.recurrence else ""
        rows.append(
            f"{r.remind_at.strftime('%d.%m.%Y'):<11} "
            f"{r.remind_at.strftime('%H:%M'):<6} {text}{flag}{rec_flag}"
        )
    return "<pre>" + "\n".join(rows) + "</pre>"


def _list_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Удалить", callback_data="rem:del_mode"),
        InlineKeyboardButton(text="✏️ Изменить", callback_data="rem:edit_mode"),
    ]])


def _delete_mode_keyboard(reminders) -> InlineKeyboardMarkup:
    pairs = [
        InlineKeyboardButton(
            text=f"🗑 {r.remind_at.strftime('%d.%m %H:%M')}",
            callback_data=f"rem:del:{r.id}",
        )
        for r in reminders
    ]
    rows = [pairs[i:i + 2] for i in range(0, len(pairs), 2)]
    rows.append([InlineKeyboardButton(text="✕ Отмена", callback_data="rem:del_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _edit_mode_keyboard(reminders) -> InlineKeyboardMarkup:
    pairs = [
        InlineKeyboardButton(
            text=f"✏️ {r.remind_at.strftime('%d.%m %H:%M')}",
            callback_data=f"rem:edit:{r.id}",
        )
        for r in reminders
    ]
    rows = [pairs[i:i + 2] for i in range(0, len(pairs), 2)]
    rows.append([InlineKeyboardButton(text="✕ Отмена", callback_data="rem:edit_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("list"))
async def cmd_list(message: Message):
    reminders = await _fetch_reminders(message.from_user.id)

    if not reminders:
        await message.answer("📭 У тебя пока нет активных напоминаний.")
        return

    await message.answer(
        f"📋 <b>Напоминания ({len(reminders)}):</b>\n\n"
        f"{_build_table(reminders)}",
        reply_markup=_list_keyboard(),
    )


@router.callback_query(F.data == "rem:del_mode")
async def handle_del_mode(callback: CallbackQuery):
    reminders = await _fetch_reminders(callback.from_user.id)
    if not reminders:
        await callback.answer("Нет активных напоминаний.", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=_delete_mode_keyboard(reminders))
    await callback.answer()


@router.callback_query(F.data == "rem:del_cancel")
async def handle_del_cancel(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=_list_keyboard())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^rem:del:(\d+)$"))
async def handle_list_delete(callback: CallbackQuery):
    reminder_id = int(re.match(r"^rem:del:(\d+)$", callback.data).group(1))

    async with AsyncSessionLocal() as session:
        query = select(Reminder).where(
            Reminder.id == reminder_id,
            Reminder.user_id == callback.from_user.id,
        )
        result = await session.execute(query)
        reminder = result.scalar_one_or_none()

        if not reminder:
            await callback.answer("Напоминание не найдено.", show_alert=True)
            return

        deleted_text = reminder.text
        reminder.is_active = False
        await session.commit()

    reminders = await _fetch_reminders(callback.from_user.id)

    if not reminders:
        await callback.message.edit_text("📭 У тебя пока нет активных напоминаний.")
    else:
        await callback.message.edit_text(
            f"📋 <b>Напоминания ({len(reminders)}):</b>\n\n"
            f"{_build_table(reminders)}",
            reply_markup=_delete_mode_keyboard(reminders),
        )

    await callback.answer(f"✅ Удалено: {deleted_text[:30]}")


@router.callback_query(F.data == "rem:edit_mode")
async def handle_edit_mode(callback: CallbackQuery):
    reminders = await _fetch_reminders(callback.from_user.id)
    if not reminders:
        await callback.answer("Нет активных напоминаний.", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=_edit_mode_keyboard(reminders))
    await callback.answer()


@router.callback_query(F.data == "rem:edit_cancel")
async def handle_edit_cancel(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=_list_keyboard())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^rem:edit:(\d+)$"))
async def handle_edit_select(callback: CallbackQuery):
    reminder_id = int(re.match(r"^rem:edit:(\d+)$", callback.data).group(1))
    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or reminder.user_id != callback.from_user.id:
            await callback.answer("Напоминание не найдено.", show_alert=True)
            return
        preview = reminder.text[:30]
        dt_str = reminder.remind_at.strftime("%d.%m.%Y %H:%M")

    await callback.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Текст", callback_data=f"rem:edit_text:{reminder_id}"),
                InlineKeyboardButton(text="⏰ Время", callback_data=f"rem:edit_time:{reminder_id}"),
            ],
            [InlineKeyboardButton(text="◀ Назад", callback_data="rem:edit_mode")],
        ])
    )
    await callback.answer(f"{preview} — {dt_str}")


@router.callback_query(F.data.regexp(r"^rem:edit_text:(\d+)$"))
async def handle_edit_text_start(callback: CallbackQuery, state: FSMContext):
    reminder_id = int(re.match(r"^rem:edit_text:(\d+)$", callback.data).group(1))
    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or reminder.user_id != callback.from_user.id:
            await callback.answer("Напоминание не найдено.", show_alert=True)
            return
        current_text = reminder.text
        dt_str = reminder.remind_at.strftime("%d.%m.%Y %H:%M")

    await state.set_state(ReminderStates.waiting_for_edit_text)
    await state.update_data(reminder_id=reminder_id, reminder_dt_str=dt_str)
    await callback.message.answer(
        f"📝 <b>Текущий текст:</b> {current_text}\n"
        f"⏰ <b>Время:</b> {dt_str}\n\n"
        f"Введи новый текст напоминания:\n\n"
        f"Для отмены: /cancel"
    )
    await callback.answer()


@router.message(ReminderStates.waiting_for_edit_text, F.text, ~F.text.startswith("/"))
async def handle_edit_text_input(message: Message, state: FSMContext):
    data = await state.get_data()
    reminder_id = data["reminder_id"]
    new_text = message.text.strip()

    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or reminder.user_id != message.from_user.id:
            await message.answer("❌ Напоминание не найдено.")
            await state.clear()
            return
        reminder.text = new_text
        dt_str = reminder.remind_at.strftime("%d.%m.%Y %H:%M")
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Текст обновлён!\n\n"
        f"📝 {new_text}\n"
        f"⏰ {dt_str}"
    )


@router.callback_query(F.data.regexp(r"^rem:edit_time:(\d+)$"))
async def handle_edit_time_start(callback: CallbackQuery, state: FSMContext):
    reminder_id = int(re.match(r"^rem:edit_time:(\d+)$", callback.data).group(1))
    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or reminder.user_id != callback.from_user.id:
            await callback.answer("Напоминание не найдено.", show_alert=True)
            return
        reminder_text = reminder.text
        original_remind_at = reminder.remind_at.isoformat()

    user_tz = await _load_user_tz(callback.from_user.id)
    _cancel_reminder_job(reminder_id)
    await state.set_state(ReminderStates.waiting_for_edit_time)
    await state.update_data(
        reminder_id=reminder_id,
        reminder_text=reminder_text,
        original_remind_at=original_remind_at,
        tz_name=user_tz.zone,
    )
    await callback.message.answer(
        f"📝 <b>Текст:</b> {reminder_text}\n"
        f"⏰ <b>Текущее время:</b> {datetime.fromisoformat(original_remind_at).strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Введи новую дату и время:\n"
        f"Например: <i>завтра в 10:00</i>, <i>20.02 в 15:00</i>, <i>через 2 часа</i>\n\n"
        f"Для отмены: /cancel"
    )
    await callback.answer()


@router.message(ReminderStates.waiting_for_edit_time, F.text, ~F.text.startswith("/"))
async def handle_edit_time_input(message: Message, state: FSMContext):
    data = await state.get_data()
    reminder_id = data["reminder_id"]
    tz_name = data.get("tz_name", settings.timezone)
    user_tz = pytz.timezone(tz_name)
    dp_s = _dateparser_settings(tz_name)

    normalized = _expand_short_dates(_normalize_time(message.text.strip()), year=_now_tz(user_tz).year)
    dt = dateparser.parse(normalized, languages=["ru"], settings=dp_s)

    if dt is None or dt <= _now_tz(user_tz):
        await message.answer(
            "❌ Не смог распознать дату/время или оно в прошлом. Попробуй ещё раз.\n"
            "Например: <i>завтра в 10:00</i>, <i>20.02 в 15:00</i>, <i>через 2 часа</i>"
        )
        return

    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or reminder.user_id != message.from_user.id:
            await message.answer("❌ Напоминание не найдено.")
            await state.clear()
            return
        reminder.remind_at = dt
        reminder.is_confirmed = False
        reminder.is_snoozed = False
        reminder.message_id = None
        await session.commit()
        schedule_reminder(reminder, tz=user_tz)

    await state.clear()
    await message.answer(
        f"✅ Время обновлено!\n\n"
        f"📝 {data['reminder_text']}\n"
        f"⏰ {dt.strftime('%d.%m.%Y %H:%M')}"
    )


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


@router.message(ReminderStates.waiting_for_delete_id, F.text, ~F.text.startswith("/"))
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
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нечего отменять.")
        return

    if current_state in (
        ReminderStates.waiting_for_reschedule.state,
        ReminderStates.waiting_for_edit_time.state,
    ):
        data = await state.get_data()
        reminder_id = data.get("reminder_id")
        original_remind_at_str = data.get("original_remind_at")
        tz_name = data.get("tz_name", settings.timezone)
        user_tz = pytz.timezone(tz_name)
        if reminder_id and original_remind_at_str:
            original_remind_at = datetime.fromisoformat(original_remind_at_str)
            now = _now_tz(user_tz)
            run_date = original_remind_at if original_remind_at > now else now
            scheduler.add_job(
                send_reminder,
                trigger=DateTrigger(timezone=user_tz, run_date=run_date),
                args=[reminder_id],
                id=f"reminder_{reminder_id}",
                replace_existing=True,
                misfire_grace_time=60,
            )

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
            if reminder.recurrence:
                us_result = await session.execute(
                    select(UserSettings).where(UserSettings.user_id == callback.from_user.id)
                )
                us = us_result.scalar_one_or_none()
                user_tz = pytz.timezone(us.timezone if us else settings.timezone)
                anchor = reminder.recurrence_anchor or reminder.remind_at
                next_dt = _next_occurrence(anchor, reminder.recurrence)
                reminder.remind_at = next_dt
                reminder.recurrence_anchor = next_dt
                reminder.is_snoozed = False
                reminder.message_id = None
                await session.commit()
                _cancel_reminder_job(reminder_id)
                schedule_reminder(reminder, tz=user_tz)
                await callback.message.edit_text(
                    f"⏰ <b>Напоминание!</b>\n\n{reminder.text}\n\n"
                    f"✅ <i>Выполнено!</i>\n"
                    f"🔁 Следующее: <b>{next_dt.strftime('%d.%m.%Y %H:%M')}</b>"
                )
            else:
                reminder.is_confirmed = True
                reminder.is_active = False
                await session.commit()
                _cancel_reminder_job(reminder_id)
                await callback.message.edit_text(
                    f"⏰ <b>Напоминание!</b>\n\n{reminder.text}\n\n✅ <i>Выполнено</i>"
                )

        elif action == "snooze":
            us_result = await session.execute(
                select(UserSettings).where(UserSettings.user_id == callback.from_user.id)
            )
            us = us_result.scalar_one_or_none()
            user_tz = pytz.timezone(us.timezone if us else settings.timezone)

            reminder.remind_at = _now_tz(user_tz) + timedelta(hours=1)
            reminder.is_confirmed = False
            reminder.is_snoozed = True
            reminder.message_id = None
            await session.commit()
            _cancel_reminder_job(reminder_id)
            scheduler.add_job(
                send_reminder,
                trigger=DateTrigger(timezone=user_tz, run_date=reminder.remind_at),
                args=[reminder_id],
                id=f"reminder_{reminder_id}",
                replace_existing=True,
                misfire_grace_time=60,
            )
            await callback.message.edit_text(
                f"⏰ <b>Напоминание!</b>\n\n{reminder.text}\n\n⏱ <i>Отложено на 1 час</i>"
            )

    await callback.answer()


@router.callback_query(F.data.regexp(r"^rem:snooze_day:(\d+)$"))
async def handle_snooze_day(callback: CallbackQuery):
    reminder_id = int(re.match(r"^rem:snooze_day:(\d+)$", callback.data).group(1))

    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or reminder.user_id != callback.from_user.id:
            await callback.answer("Напоминание не найдено.", show_alert=True)
            return

        us_result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == callback.from_user.id)
        )
        us = us_result.scalar_one_or_none()
        user_tz = pytz.timezone(us.timezone if us else settings.timezone)

        new_time = reminder.remind_at + timedelta(days=1)
        if new_time <= _now_tz(user_tz):
            new_time = _now_tz(user_tz) + timedelta(days=1)

        reminder_text = reminder.text
        reminder.remind_at = new_time
        reminder.is_confirmed = False
        reminder.is_snoozed = True
        reminder.message_id = None
        await session.commit()

    _cancel_reminder_job(reminder_id)
    scheduler.add_job(
        send_reminder,
        trigger=DateTrigger(timezone=user_tz, run_date=new_time),
        args=[reminder_id],
        id=f"reminder_{reminder_id}",
        replace_existing=True,
        misfire_grace_time=60,
    )
    await callback.message.edit_text(
        f"⏰ <b>Напоминание!</b>\n\n{reminder_text}\n\n"
        f"📅 <i>Перенесено на {new_time.strftime('%d.%m.%Y %H:%M')}</i>"
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^rem:reschedule:(\d+)$"))
async def handle_reschedule_start(callback: CallbackQuery, state: FSMContext):
    reminder_id = int(re.match(r"^rem:reschedule:(\d+)$", callback.data).group(1))

    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or reminder.user_id != callback.from_user.id:
            await callback.answer("Напоминание не найдено.", show_alert=True)
            return
        reminder_text = reminder.text
        original_remind_at = reminder.remind_at.isoformat()

    user_tz = await _load_user_tz(callback.from_user.id)
    _cancel_reminder_job(reminder_id)
    await state.set_state(ReminderStates.waiting_for_reschedule)
    await state.update_data(
        reminder_id=reminder_id,
        reminder_text=reminder_text,
        original_remind_at=original_remind_at,
        tz_name=user_tz.zone,
    )
    await callback.message.edit_text(
        f"⏰ <b>Напоминание!</b>\n\n{reminder_text}\n\n"
        f"✏️ <i>На какое время перенести? Введи дату и время:</i>\n"
        f"Например: <i>завтра в 10:00</i>, <i>20.02 в 15:00</i>, <i>через 2 часа</i>\n\n"
        f"Для отмены: /cancel"
    )
    await callback.answer()


@router.message(ReminderStates.waiting_for_reschedule, F.text, ~F.text.startswith("/"))
async def handle_reschedule_input(message: Message, state: FSMContext):
    data = await state.get_data()
    reminder_id = data["reminder_id"]
    tz_name = data.get("tz_name", settings.timezone)
    user_tz = pytz.timezone(tz_name)
    dp_s = _dateparser_settings(tz_name)

    normalized = _expand_short_dates(_normalize_time(message.text.strip()), year=_now_tz(user_tz).year)
    dt = dateparser.parse(normalized, languages=["ru"], settings=dp_s)

    if dt is None or dt <= _now_tz(user_tz):
        await message.answer(
            "❌ Не смог распознать дату/время или оно в прошлом. Попробуй ещё раз.\n"
            "Например: <i>завтра в 10:00</i>, <i>20.02 в 15:00</i>, <i>через 2 часа</i>"
        )
        return

    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or reminder.user_id != message.from_user.id:
            await message.answer("❌ Напоминание не найдено.")
            await state.clear()
            return
        reminder.remind_at = dt
        reminder.is_confirmed = False
        reminder.is_snoozed = True
        reminder.message_id = None
        await session.commit()

    scheduler.add_job(
        send_reminder,
        trigger=DateTrigger(timezone=user_tz, run_date=dt),
        args=[reminder_id],
        id=f"reminder_{reminder_id}",
        replace_existing=True,
        misfire_grace_time=60,
    )
    await state.clear()
    await message.answer(
        f"✅ Напоминание перенесено!\n\n"
        f"📝 {data['reminder_text']}\n"
        f"⏰ {dt.strftime('%d.%m.%Y %H:%M')}"
    )


dp.include_router(router)