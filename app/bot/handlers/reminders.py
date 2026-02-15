"""Reminder handlers"""
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from app.bot.bot import dp
from app.database import Reminder
from app.database.base import AsyncSessionLocal


router = Router()


class ReminderStates(StatesGroup):
    """States for creating a reminder"""
    waiting_for_text = State()
    waiting_for_datetime = State()


@router.message(Command("remind"))
async def cmd_remind(message: Message, state: FSMContext):
    """Start creating a reminder"""
    await state.set_state(ReminderStates.waiting_for_text)
    await message.answer(
        "📝 Отлично! Давай создадим напоминание.\n\n"
        "Введи текст напоминания:"
    )


@router.message(ReminderStates.waiting_for_text)
async def process_reminder_text(message: Message, state: FSMContext):
    """Process reminder text"""
    await state.update_data(text=message.text)
    await state.set_state(ReminderStates.waiting_for_datetime)
    await message.answer(
        "⏰ Отлично! Теперь укажи дату и время напоминания.\n\n"
        "Формат: ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "Например: 15.02.2026 18:00"
    )


@router.message(ReminderStates.waiting_for_datetime)
async def process_reminder_datetime(message: Message, state: FSMContext):
    """Process reminder datetime"""
    try:
        # Parse datetime
        remind_at = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
        
        # Check if datetime is in the future
        if remind_at <= datetime.now():
            await message.answer(
                "❌ Дата и время должны быть в будущем!\n"
                "Попробуй еще раз:"
            )
            return
        
        # Get reminder text from state
        data = await state.get_data()
        text = data.get("text")
        
        # Save reminder to database
        async with AsyncSessionLocal() as session:
            reminder = Reminder(
                user_id=message.from_user.id,
                text=text,
                remind_at=remind_at,
                is_sent=False,
                is_active=True
            )
            session.add(reminder)
            await session.commit()
        
        await message.answer(
            f"✅ Напоминание создано!\n\n"
            f"📝 Текст: {text}\n"
            f"⏰ Время: {remind_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Я напомню тебе в указанное время!"
        )
        await state.clear()
        
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты и времени!\n\n"
            "Используй формат: ДД.ММ.ГГГГ ЧЧ:ММ\n"
            "Например: 15.02.2026 18:00"
        )


@router.message(Command("list"))
async def cmd_list(message: Message):
    """Show user's reminders"""
    async with AsyncSessionLocal() as session:
        query = select(Reminder).where(
            Reminder.user_id == message.from_user.id,
            Reminder.is_active == True,
            Reminder.is_sent == False
        ).order_by(Reminder.remind_at)
        
        result = await session.execute(query)
        reminders = result.scalars().all()
    
    if not reminders:
        await message.answer("📭 У тебя пока нет активных напоминаний.")
        return
    
    text = "📋 <b>Твои напоминания:</b>\n\n"
    for i, reminder in enumerate(reminders, 1):
        text += (
            f"{i}. <b>ID:</b> {reminder.id}\n"
            f"   📝 {reminder.text}\n"
            f"   ⏰ {reminder.remind_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        )
    
    text += "Для удаления используй /delete [ID]"
    await message.answer(text)


@router.message(Command("delete"))
async def cmd_delete(message: Message):
    """Delete a reminder"""
    try:
        # Extract reminder ID from command
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                "❌ Укажи ID напоминания!\n"
                "Например: /delete 1"
            )
            return
        
        reminder_id = int(parts[1])
        
        async with AsyncSessionLocal() as session:
            query = select(Reminder).where(
                Reminder.id == reminder_id,
                Reminder.user_id == message.from_user.id
            )
            result = await session.execute(query)
            reminder = result.scalar_one_or_none()
            
            if not reminder:
                await message.answer("❌ Напоминание не найдено!")
                return
            
            reminder.is_active = False
            await session.commit()
        
        await message.answer("✅ Напоминание удалено!")
        
    except ValueError:
        await message.answer("❌ Неверный ID напоминания!")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Cancel current action"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нечего отменять.")
        return
    
    await state.clear()
    await message.answer("✅ Действие отменено.")


# Register router
dp.include_router(router)
