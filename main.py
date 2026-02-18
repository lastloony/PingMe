"""Точка входа в приложение"""
import asyncio
import logging

import uvicorn
from aiogram.types import BotCommand

from app.config import settings
from app.database import init_db
from app.bot.bot import bot, dp
from app.bot.handlers import basic, reminders, settings, fallback  # noqa: F401 — регистрируют роутеры в dp
from app.services.scheduler import start_scheduler, stop_scheduler, load_pending_reminders


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def on_startup():
    """Действия при старте бота"""
    logger.info("Инициализация базы данных...")
    await init_db()

    logger.info("Запуск планировщика напоминаний...")
    start_scheduler()

    logger.info("Загрузка незавершённых напоминаний...")
    await load_pending_reminders()

    logger.info("Установка меню команд...")
    await bot.set_my_commands([
        BotCommand(command="list",     description="Мои напоминания"),
        BotCommand(command="delete",   description="Удалить напоминание /delete"),
        BotCommand(command="settings", description="Настройки"),
        BotCommand(command="cancel",   description="Отменить текущее действие"),
        BotCommand(command="help",     description="Справка"),
    ])

    logger.info("Бот успешно запущен!")


async def on_shutdown():
    """Действия при остановке бота"""
    logger.info("Остановка планировщика...")
    stop_scheduler()

    logger.info("Закрытие сессии бота...")
    await bot.session.close()

    logger.info("Бот остановлен.")


async def start_bot():
    """Запускает Telegram-бота в режиме polling"""
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Запуск polling...")
    await dp.start_polling(bot)


async def start_api():
    """Запускает FastAPI-сервер через uvicorn"""
    config = uvicorn.Config(
        "app.api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Запускает бота и API одновременно"""
    logger.info("Запуск PingMe...")

    await asyncio.gather(
        start_bot(),
        start_api()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Приложение остановлено пользователем")