"""Сервис планировщика напоминаний"""
import logging
from datetime import datetime, timedelta

import pytz
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from app.bot.bot import bot
from app.config import settings
from app.database import Reminder
from app.database.base import AsyncSessionLocal

_TZ = pytz.timezone(settings.timezone)


def _now() -> datetime:
    """Текущее время в московском часовом поясе (наивный datetime)."""
    return datetime.now(_TZ).replace(tzinfo=None)

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

REMINDER_REPEAT_MINUTES = 15


def _build_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Выполнено", callback_data=f"rem:done:{reminder_id}"),
        InlineKeyboardButton(text="⏱ Отложить на 1ч", callback_data=f"rem:snooze:{reminder_id}"),
    ]])


async def send_reminder(reminder_id: int):
    """Отправляет напоминание пользователю с кнопками подтверждения"""
    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or not reminder.is_active or reminder.is_confirmed:
            return
        try:
            msg = await bot.send_message(
                chat_id=reminder.user_id,
                text=f"⏰ <b>Напоминание!</b>\n\n{reminder.text}",
                reply_markup=_build_keyboard(reminder_id),
            )
            reminder.message_id = msg.message_id
            await session.commit()

            # Планируем повтор через 15 минут если пользователь не нажал кнопку
            repeat_time = _now() + timedelta(minutes=REMINDER_REPEAT_MINUTES)
            scheduler.add_job(
                send_reminder,
                trigger=DateTrigger(run_date=repeat_time),
                args=[reminder_id],
                id=f"reminder_{reminder_id}",
                replace_existing=True,
                misfire_grace_time=60,
            )
            logger.info(f"Напоминание {reminder_id} отправлено, повтор через {REMINDER_REPEAT_MINUTES} мин")
        except Exception as e:
            logger.error(f"Ошибка при отправке напоминания {reminder_id}: {e}")


def schedule_reminder(reminder: Reminder):
    """Добавляет одноразовый job для конкретного напоминания"""
    scheduler.add_job(
        send_reminder,
        trigger=DateTrigger(run_date=reminder.remind_at),
        args=[reminder.id],
        id=f"reminder_{reminder.id}",
        replace_existing=True,
        misfire_grace_time=60,
    )
    logger.info(f"Напоминание {reminder.id} запланировано на {reminder.remind_at}")


async def load_pending_reminders():
    """Загружает все неотправленные напоминания из БД и планирует их при старте"""
    async with AsyncSessionLocal() as session:
        query = select(Reminder).where(
            Reminder.is_active == True,
            Reminder.is_confirmed == False,
        )
        result = await session.execute(query)
        reminders = result.scalars().all()

    now = _now()
    scheduled = 0
    overdue = 0

    for reminder in reminders:
        if reminder.remind_at <= now:
            scheduler.add_job(
                send_reminder,
                trigger=DateTrigger(run_date=now),
                args=[reminder.id],
                id=f"reminder_{reminder.id}",
                replace_existing=True,
            )
            overdue += 1
        else:
            schedule_reminder(reminder)
            scheduled += 1

    logger.info(f"Загружено напоминаний: {scheduled} запланировано, {overdue} просрочено")


def start_scheduler():
    """Запускает планировщик"""
    scheduler.start()


def stop_scheduler():
    """Останавливает планировщик"""
    scheduler.shutdown()
