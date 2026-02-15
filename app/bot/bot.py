"""Инициализация Telegram-бота"""
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings

# Создаём экземпляр бота с HTML-разметкой по умолчанию
bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# Создаём диспетчер
dp = Dispatcher()