"""Хендлер настроек пользователя"""
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from sqlalchemy import select

from app.bot.bot import dp
from app.database import UserSettings, DEFAULT_SNOOZE_MINUTES, DEFAULT_TIMEZONE
from app.database.base import AsyncSessionLocal

router = Router()

SNOOZE_OPTIONS = [5, 15, 30]

TIMEZONE_OPTIONS = [
    ("UTC+2",  "Europe/Kaliningrad"),
    ("UTC+3",  "Europe/Moscow"),
    ("UTC+4",  "Europe/Samara"),
    ("UTC+5",  "Asia/Yekaterinburg"),
    ("UTC+6",  "Asia/Omsk"),
    ("UTC+7",  "Asia/Krasnoyarsk"),
    ("UTC+8",  "Asia/Irkutsk"),
    ("UTC+9",  "Asia/Yakutsk"),
    ("UTC+10", "Asia/Vladivostok"),
    ("UTC+11", "Asia/Magadan"),
    ("UTC+12", "Asia/Kamchatka"),
]

_TZ_BY_ID = {tz_id: label for label, tz_id in TIMEZONE_OPTIONS}
_VALID_TZ_IDS = set(_TZ_BY_ID)


def _tz_label(tz_id: str) -> str:
    return _TZ_BY_ID.get(tz_id, tz_id)


def _settings_text(snooze_minutes: int, tz_id: str) -> str:
    return (
        f"⚙️ <b>Настройки</b>\n\n"
        f"Повтор напоминания: <b>{snooze_minutes} мин</b>\n"
        f"Часовой пояс: <b>{_tz_label(tz_id)}</b>"
    )


def _settings_keyboard(current_snooze: int, current_tz: str, tz_expanded: bool = False) -> InlineKeyboardMarkup:
    snooze_row = [
        InlineKeyboardButton(
            text=f"{'✅ ' if current_snooze == m else ''}{m} мин",
            callback_data=f"settings:snooze:{m}",
        )
        for m in SNOOZE_OPTIONS
    ]

    if tz_expanded:
        tz_buttons = [
            InlineKeyboardButton(
                text=f"{'✅ ' if current_tz == tz_id else ''}{label}",
                callback_data=f"settings:tz:{tz_id}",
            )
            for label, tz_id in TIMEZONE_OPTIONS
        ]
        tz_rows = [tz_buttons[i:i + 4] for i in range(0, len(tz_buttons), 4)]
        close_row = [InlineKeyboardButton(text="✕ Свернуть", callback_data="settings:tz_close")]
        return InlineKeyboardMarkup(inline_keyboard=[snooze_row] + tz_rows + [close_row])
    else:
        tz_row = [
            InlineKeyboardButton(
                text=f"🌍 Часовой пояс: {_tz_label(current_tz)} ▸",
                callback_data="settings:tz_open",
            )
        ]
        return InlineKeyboardMarkup(inline_keyboard=[snooze_row, tz_row])


async def _get_or_create_settings(user_id: int, session) -> UserSettings:
    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        obj = UserSettings(user_id=user_id, snooze_minutes=DEFAULT_SNOOZE_MINUTES, timezone=DEFAULT_TIMEZONE)
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
    return obj


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    async with AsyncSessionLocal() as session:
        obj = await _get_or_create_settings(message.from_user.id, session)

    await message.answer(
        _settings_text(obj.snooze_minutes, obj.timezone),
        reply_markup=_settings_keyboard(obj.snooze_minutes, obj.timezone),
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
        current_tz = obj.timezone

    await callback.message.edit_text(
        _settings_text(minutes, current_tz),
        reply_markup=_settings_keyboard(minutes, current_tz),
    )
    await callback.answer(f"✅ Интервал повтора: {minutes} мин")


@router.callback_query(F.data == "settings:tz_open")
async def handle_tz_open(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        obj = await _get_or_create_settings(callback.from_user.id, session)

    await callback.message.edit_reply_markup(
        reply_markup=_settings_keyboard(obj.snooze_minutes, obj.timezone, tz_expanded=True),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:tz_close")
async def handle_tz_close(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        obj = await _get_or_create_settings(callback.from_user.id, session)

    await callback.message.edit_reply_markup(
        reply_markup=_settings_keyboard(obj.snooze_minutes, obj.timezone, tz_expanded=False),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^settings:tz:(.+)$"))
async def handle_timezone_setting(callback: CallbackQuery):
    tz_id = re.match(r"^settings:tz:(.+)$", callback.data).group(1)
    if tz_id not in _VALID_TZ_IDS:
        await callback.answer("Недопустимый часовой пояс.", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        obj = await _get_or_create_settings(callback.from_user.id, session)
        obj.timezone = tz_id
        await session.commit()
        current_snooze = obj.snooze_minutes

    await callback.message.edit_text(
        _settings_text(current_snooze, tz_id),
        reply_markup=_settings_keyboard(current_snooze, tz_id),
    )
    await callback.answer(f"✅ Часовой пояс: {_tz_label(tz_id)}")


dp.include_router(router)