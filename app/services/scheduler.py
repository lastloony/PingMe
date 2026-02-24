"""Сервис планировщика напоминаний"""
import logging
from datetime import datetime, timedelta

import pytz
from dateutil.relativedelta import relativedelta
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from app.bot.bot import bot
from app.config import settings
from app.database import Reminder, UserSettings, DEFAULT_SNOOZE_MINUTES, DEFAULT_TIMEZONE
from app.database.base import AsyncSessionLocal

_TZ = pytz.timezone(settings.timezone)


def _now() -> datetime:
    """Текущее время в московском часовом поясе (наивный datetime)."""
    return datetime.now(_TZ).replace(tzinfo=None)


def _now_tz(tz: pytz.BaseTzInfo) -> datetime:
    """Текущее время в указанном часовом поясе (наивный datetime)."""
    return datetime.now(tz).replace(tzinfo=None)


logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone=_TZ)

REMINDER_REPEAT_MINUTES = 1 if settings.debug else DEFAULT_SNOOZE_MINUTES


def _build_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Выполнено", callback_data=f"rem:done:{reminder_id}"),
            InlineKeyboardButton(text="⏱ +1 час", callback_data=f"rem:snooze:{reminder_id}"),
        ],
        [
            InlineKeyboardButton(text="📅 +1 день", callback_data=f"rem:snooze_day:{reminder_id}"),
            InlineKeyboardButton(text="✏️ Перенести", callback_data=f"rem:reschedule:{reminder_id}"),
        ],
    ])


async def send_reminder(reminder_id: int):
    """Отправляет напоминание пользователю с кнопками подтверждения"""
    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or not reminder.is_active or reminder.is_confirmed:
            return

        user_settings = await session.execute(
            select(UserSettings).where(UserSettings.user_id == reminder.user_id)
        )
        settings_obj = user_settings.scalar_one_or_none()
        repeat_minutes = settings_obj.snooze_minutes if settings_obj else REMINDER_REPEAT_MINUTES
        user_tz = pytz.timezone(settings_obj.timezone if settings_obj else DEFAULT_TIMEZONE)

        try:
            if reminder.message_id:
                try:
                    await bot.delete_message(chat_id=reminder.user_id, message_id=reminder.message_id)
                except Exception:
                    pass

            msg = await bot.send_message(
                chat_id=reminder.user_id,
                text=f"⏰ <b>Напоминание!</b>\n\n{reminder.text}",
                reply_markup=_build_keyboard(reminder_id),
            )
            reminder.message_id = msg.message_id
            reminder.is_snoozed = False
            await session.commit()

            repeat_time = _now_tz(user_tz) + timedelta(minutes=repeat_minutes)
            scheduler.add_job(
                send_reminder,
                trigger=DateTrigger(timezone=user_tz, run_date=repeat_time),
                args=[reminder_id],
                id=f"reminder_{reminder_id}",
                replace_existing=True,
                misfire_grace_time=60,
            )
            logger.info(f"Напоминание {reminder_id} отправлено, повтор через {repeat_minutes} мин")
        except Exception as e:
            logger.error(f"Ошибка при отправке напоминания {reminder_id}: {e}")


def _next_occurrence(remind_at: datetime, recurrence: str) -> datetime:
    """Возвращает следующий datetime для периодического напоминания."""
    if recurrence == "hourly":
        return remind_at + timedelta(hours=1)
    elif recurrence == "daily":
        return remind_at + timedelta(days=1)
    elif recurrence == "weekly":
        return remind_at + timedelta(weeks=1)
    elif recurrence == "monthly":
        return remind_at + relativedelta(months=1)
    elif recurrence == "yearly":
        return remind_at + relativedelta(years=1)
    raise ValueError(f"Unknown recurrence: {recurrence}")


def schedule_reminder(reminder: Reminder, tz: pytz.BaseTzInfo | None = None):
    """Добавляет одноразовый job для конкретного напоминания"""
    job_tz = tz if tz is not None else _TZ
    scheduler.add_job(
        send_reminder,
        trigger=DateTrigger(timezone=job_tz, run_date=reminder.remind_at),
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

        user_ids = list({r.user_id for r in reminders})
        if user_ids:
            us_result = await session.execute(
                select(UserSettings).where(UserSettings.user_id.in_(user_ids))
            )
            tz_map = {
                us.user_id: pytz.timezone(us.timezone)
                for us in us_result.scalars().all()
            }
        else:
            tz_map = {}

    scheduled = 0
    overdue = 0

    for reminder in reminders:
        user_tz = tz_map.get(reminder.user_id, _TZ)
        now = _now_tz(user_tz)
        if reminder.remind_at <= now:
            if reminder.recurrence:
                anchor = reminder.recurrence_anchor or reminder.remind_at
                next_dt = anchor
                while next_dt <= now:
                    next_dt = _next_occurrence(next_dt, reminder.recurrence)
                async with AsyncSessionLocal() as update_session:
                    r = await update_session.get(Reminder, reminder.id)
                    if r:
                        r.remind_at = next_dt
                        r.recurrence_anchor = next_dt
                        await update_session.commit()
                reminder.remind_at = next_dt
                schedule_reminder(reminder, tz=user_tz)
            else:
                scheduler.add_job(
                    send_reminder,
                    trigger=DateTrigger(timezone=user_tz, run_date=now),
                    args=[reminder.id],
                    id=f"reminder_{reminder.id}",
                    replace_existing=True,
                )
            overdue += 1
        else:
            schedule_reminder(reminder, tz=user_tz)
            scheduled += 1

    logger.info(f"Загружено напоминаний: {scheduled} запланировано, {overdue} просрочено")


def start_scheduler():
    """Запускает планировщик"""
    scheduler.start()


def stop_scheduler():
    """Останавливает планировщик"""
    scheduler.shutdown()