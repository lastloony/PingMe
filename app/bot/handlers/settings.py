"""Хендлер настроек пользователя"""
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from sqlalchemy import select

from app.bot.bot import dp
from app.database import UserSettings, DEFAULT_SNOOZE_MINUTES
from app.database.base import AsyncSessionLocal

router = Router()

SNOOZE_OPTIONS = [5, 15, 30]


def _settings_keyboard(current_snooze: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=f"{'✅ ' if current_snooze == m else ''}{m} мин",
            callback_data=f"settings:snooze:{m}",
        )
        for m in SNOOZE_OPTIONS
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


async def _get_or_create_settings(user_id: int, session) -> UserSettings:
    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        obj = UserSettings(user_id=user_id, snooze_minutes=DEFAULT_SNOOZE_MINUTES)
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
    return obj


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    async with AsyncSessionLocal() as session:
        obj = await _get_or_create_settings(message.from_user.id, session)

    await message.answer(
        f"⚙️ <b>Настройки</b>\n\n"
        f"Повтор напоминания: <b>{obj.snooze_minutes} мин</b>\n\n"
        f"Выбери интервал повтора:",
        reply_markup=_settings_keyboard(obj.snooze_minutes),
    )


@router.callback_query(F.data.regexp(r"^settings:snooze:(\d+)$"))
async def handle_snooze_setting(callback: CallbackQuery):
    minutes = int(re.match(r"^settings:snooze:(\d+)$", callback.data).group(1))
    if minutes not in SNOOZE_OPTIONS:
        await callback.answer("Недопустимое значение.", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        obj = await _get_or_create_settings(callback.from_user.id, session)
        obj.snooze_minutes = minutes
        await session.commit()

    await callback.message.edit_text(
        f"⚙️ <b>Настройки</b>\n\n"
        f"Повтор напоминания: <b>{minutes} мин</b>\n\n"
        f"Выбери интервал повтора:",
        reply_markup=_settings_keyboard(minutes),
    )
    await callback.answer(f"✅ Интервал повтора: {minutes} мин")


dp.include_router(router)