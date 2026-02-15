"""Pydantic schemas for API"""
from datetime import datetime
from pydantic import BaseModel, Field


class ReminderCreate(BaseModel):
    """Schema for creating a reminder"""
    user_id: int = Field(..., description="Telegram user ID")
    text: str = Field(..., min_length=1, max_length=1000, description="Reminder text")
    remind_at: datetime = Field(..., description="When to send the reminder")


class ReminderResponse(BaseModel):
    """Schema for reminder response"""
    id: int
    user_id: int
    text: str
    remind_at: datetime
    is_sent: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}
