"""Хендлеры напоминаний с парсингом естественного языка"""
import re
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from dateparser.search import search_dates
from sqlalchemy import select

from app.bot.bot import dp
from app.database import Reminder
from app.database.base import AsyncSessionLocal
from app.services.scheduler import schedule_reminder


router = Router()

# Настройки парсера дат — предпочитаем будущее время, формат ДД.ММ.ГГГГ
DATEPARSER_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "RETURN_AS_TIMEZONE_AWARE": False,
    "DATE_ORDER": "DMY",
}

# Регулярка для отсечения префикса «напомни [мне]»
_PREFIX_RE = re.compile(
    r"^напомни(те)?\s*(мне\s*)?",
    flags=re.IGNORECASE,
)


class ReminderStates(StatesGroup):
    waiting_for_reminder = State()


def _parse_reminder(raw: str) -> tuple[str, datetime] | None:
    """
    Извлекает (текст, дату) из произвольной строки на русском.
    Возвращает None, если дату распознать не удалось.
    """
    text = _PREFIX_RE.sub("", raw).strip()

    results = search_dates(text, languages=["ru"], settings=DATEPARSER_SETTINGS)
    if not results:
        # Пробуем исходную строку без удаления префикса
        results = search_dates(raw, languages=["ru"], settings=DATEPARSER_SETTINGS)
    if not results:
        return None

    # Берём первое найденное временно́е выражение
    date_string, dt = results[0]

    # Убираем дату из текста — остаток и есть суть напоминания
    reminder_text = text.replace(date_string, "").strip()
    # Чистим лишние знаки препинания / союзы по краям
    reminder_text = re.sub(r"^[\s,\-–—]+|[\s,\-–—]+$", "", reminder_text)
    if not reminder_text:
        reminder_text = raw  # если ничего не осталось — сохраняем оригинал

    return reminder_text, dt


@router.message(F.text.regexp(r"(?i)^напомни(те)?(\s|$)"))
async def remind_from_text(message: Message, state: FSMContext):
    """Создаёт напоминание из обычного сообщения вида «напомни через 5 минут...»"""
    await _handle_reminder_text(message, message.text, state)


async def _handle_reminder_text(message: Message, raw: str, state: FSMContext):
    """Парсит строку и сохраняет напоминание в БД."""
    parsed = _parse_reminder(raw)

    if parsed is None:
        await message.answer(
            "❌ Не смог распознать дату или время.\n\n"
            "Попробуй иначе, например:\n"
            "• <i>напомни через 30 минут позвонить</i>\n"
            "• <i>напомни завтра в 10:00 встреча</i>"
        )
        return

    reminder_text, remind_at = parsed

    if remind_at <= datetime.now():
        await message.answer(
            "❌ Время напоминания уже в прошлом!\n"
            "Укажи время в будущем."
        )
        return

    async with AsyncSessionLocal() as session:
        reminder = Reminder(
            user_id=message.from_user.id,
            text=reminder_text,
            remind_at=remind_at,
        )
        session.add(reminder)
        await session.commit()
        await session.refresh(reminder)  # получаем присвоенный id
        schedule_reminder(reminder)

    await state.clear()
    await message.answer(
        f"✅ Напоминание создано!\n\n"
        f"📝 {reminder_text}\n"
        f"⏰ {remind_at.strftime('%d.%m.%Y %H:%M')}"
    )


@router.message(Command("list"))
async def cmd_list(message: Message):
    """Показывает список активных напоминаний пользователя"""
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
    """Удаляет напоминание по ID"""
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
    """Отменяет текущее действие"""
    if await state.get_state() is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("✅ Действие отменено.")


# Регистрируем роутер в диспетчере
dp.include_router(router)