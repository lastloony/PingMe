"""Сервис планировщика напоминаний"""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from app.bot.bot import bot
from app.database import Reminder
from app.database.base import AsyncSessionLocal

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def send_reminder(reminder_id: int):
    """Отправляет напоминание пользователю и помечает его как отправленное"""
    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, reminder_id)
        if not reminder or reminder.is_sent or not reminder.is_active:
            return
        try:
            await bot.send_message(
                chat_id=reminder.user_id,
                text=f"⏰ <b>Напоминание!</b>\n\n{reminder.text}"
            )
            reminder.is_sent = True
            await session.commit()
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
        misfire_grace_time=60,  # запустить, даже если опоздали до 60 секунд
    )
    logger.info(f"Напоминание {reminder.id} запланировано на {reminder.remind_at}")


async def load_pending_reminders():
    """Загружает все неотправленные напоминания из БД и планирует их при старте"""
    async with AsyncSessionLocal() as session:
        query = select(Reminder).where(
            Reminder.is_active == True,
            Reminder.is_sent == False,
        )
        result = await session.execute(query)
        reminders = result.scalars().all()

    now = datetime.now()
    scheduled = 0
    overdue = 0

    for reminder in reminders:
        if reminder.remind_at <= now:
            # Просроченное — отправляем сразу
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