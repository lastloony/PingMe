"""FastAPI-приложение"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from .routes import router


app = FastAPI(
    title="PingMe API",
    description="REST API для Telegram-бота напоминаний",
    version="0.1.0",
    debug=settings.debug
)

# CORS — разрешаем все источники (для разработки)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root():
    """Проверка работоспособности API"""
    return {
        "status": "ok",
        "service": "PingMe API",
        "version": "0.1.0"
    }


@app.get("/health")
async def health():
    """Healthcheck"""
    return {"status": "healthy"}