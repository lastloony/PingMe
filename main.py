"""Main application entry point"""
import asyncio
import logging

import uvicorn
from aiogram import Bot

from app.config import settings
from app.database import init_db
from app.bot.bot import bot, dp
from app.bot.handlers import basic, reminders
from app.services.scheduler import start_scheduler, stop_scheduler


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def on_startup():
    """Actions on bot startup"""
    logger.info("Initializing database...")
    await init_db()
    
    logger.info("Starting reminder scheduler...")
    start_scheduler()
    
    logger.info("Bot started successfully!")


async def on_shutdown():
    """Actions on bot shutdown"""
    logger.info("Stopping reminder scheduler...")
    stop_scheduler()
    
    logger.info("Closing bot session...")
    await bot.session.close()
    
    logger.info("Bot stopped!")


async def start_bot():
    """Start the Telegram bot"""
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    logger.info("Starting bot polling...")
    await dp.start_polling(bot)


async def start_api():
    """Start the FastAPI server"""
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
    """Run both bot and API"""
    logger.info("Starting PingMe application...")
    
    # Run bot and API concurrently
    await asyncio.gather(
        start_bot(),
        start_api()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
