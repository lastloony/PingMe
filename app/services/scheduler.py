"""Reminder scheduler service"""
import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.bot.bot import bot
from app.database import Reminder
from app.database.base import AsyncSessionLocal


scheduler = AsyncIOScheduler()


async def check_reminders():
    """Check and send due reminders"""
    async with AsyncSessionLocal() as session:
        # Get all active reminders that are due
        query = select(Reminder).where(
            Reminder.is_active == True,
            Reminder.is_sent == False,
            Reminder.remind_at <= datetime.now()
        )
        
        result = await session.execute(query)
        reminders = result.scalars().all()
        
        for reminder in reminders:
            try:
                # Send reminder to user
                await bot.send_message(
                    chat_id=reminder.user_id,
                    text=f"⏰ <b>Напоминание!</b>\n\n{reminder.text}"
                )
                
                # Mark as sent
                reminder.is_sent = True
                await session.commit()
                
            except Exception as e:
                print(f"Error sending reminder {reminder.id}: {e}")


def start_scheduler():
    """Start the reminder scheduler"""
    # Check reminders every minute
    scheduler.add_job(
        check_reminders,
        trigger=IntervalTrigger(minutes=1),
        id="check_reminders",
        replace_existing=True
    )
    scheduler.start()


def stop_scheduler():
    """Stop the reminder scheduler"""
    scheduler.shutdown()
