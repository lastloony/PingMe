"""Basic bot handlers"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.bot import dp

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command"""
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я бот-напоминалка PingMe. Я помогу тебе не забыть о важных делах!\n\n"
        "Доступные команды:\n"
        "/remind - Создать напоминание\n"
        "/list - Показать мои напоминания\n"
        "/help - Справка"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command"""
    await message.answer(
        "📚 <b>Справка по использованию бота</b>\n\n"
        "<b>Команды:</b>\n"
        "/start - Начать работу с ботом\n"
        "/remind - Создать новое напоминание\n"
        "/list - Показать список напоминаний\n"
        "/delete - Удалить напоминание\n"
        "/cancel - Отменить текущее действие\n\n"
        "<b>Как создать напоминание:</b>\n"
        "1. Отправь команду /remind\n"
        "2. Введи текст напоминания\n"
        "3. Укажи дату и время в формате: ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "   Например: 15.02.2026 18:00\n\n"
        "Я отправлю тебе уведомление в указанное время! ⏰"
    )


# Register router
dp.include_router(router)
