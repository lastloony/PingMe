"""API routes"""
from typing import List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Reminder
from .schemas import ReminderCreate, ReminderResponse


router = APIRouter(tags=["reminders"])


@router.get("/reminders", response_model=List[ReminderResponse])
async def get_reminders(
    user_id: int,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """Get all reminders for a user"""
    query = select(Reminder).where(
        Reminder.user_id == user_id,
        Reminder.is_active == True
    ).offset(skip).limit(limit)
    
    result = await db.execute(query)
    reminders = result.scalars().all()
    return reminders


@router.post("/reminders", response_model=ReminderResponse)
async def create_reminder(
    reminder: ReminderCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new reminder"""
    db_reminder = Reminder(
        user_id=reminder.user_id,
        text=reminder.text,
        remind_at=reminder.remind_at,
        is_sent=False,
        is_active=True
    )
    db.add(db_reminder)
    await db.flush()
    await db.refresh(db_reminder)
    return db_reminder


@router.delete("/reminders/{reminder_id}")
async def delete_reminder(
    reminder_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete a reminder"""
    query = select(Reminder).where(
        Reminder.id == reminder_id,
        Reminder.user_id == user_id
    )
    result = await db.execute(query)
    reminder = result.scalar_one_or_none()
    
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    
    reminder.is_active = False
    await db.flush()
    
    return {"status": "deleted", "id": reminder_id}
