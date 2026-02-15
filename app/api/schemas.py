"""Pydantic-схемы для API"""
from datetime import datetime
from pydantic import BaseModel, Field


class ReminderCreate(BaseModel):
    """Схема для создания напоминания"""
    user_id: int = Field(..., description="Telegram ID пользователя")
    text: str = Field(..., min_length=1, max_length=1000, description="Текст напоминания")
    remind_at: datetime = Field(..., description="Дата и время отправки")


class ReminderResponse(BaseModel):
    """Схема ответа с данными напоминания"""
    id: int
    user_id: int
    text: str
    remind_at: datetime
    is_sent: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}