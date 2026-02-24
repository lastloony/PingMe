"""
Тесты хендлера настроек пользователя и интеграции с планировщиком.

Запуск:
    pytest tests/test_settings.py -v
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.settings import (
    cmd_settings,
    handle_snooze_setting,
    handle_tz_open,
    handle_tz_close,
    handle_timezone_setting,
    SNOOZE_OPTIONS,
    TIMEZONE_OPTIONS,
)
from app.database import DEFAULT_SNOOZE_MINUTES
from app.services.scheduler import send_reminder


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_message(user_id: int = 42):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.answer = AsyncMock()
    return msg


def _make_callback(data: str, user_id: int = 42):
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def _make_user_settings(snooze_minutes: int = DEFAULT_SNOOZE_MINUTES, timezone: str = "Europe/Moscow"):
    obj = MagicMock()
    obj.snooze_minutes = snooze_minutes
    obj.timezone = timezone
    return obj


def _make_session(settings_obj=None):
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = settings_obj
    session.execute = AsyncMock(return_value=mock_result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_reminder_session(reminder, settings_obj=None):
    session = AsyncMock()
    session.get = AsyncMock(return_value=reminder)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = settings_obj
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_reminder_obj(id=1, user_id=100, text="тест"):
    r = MagicMock()
    r.id = id
    r.user_id = user_id
    r.text = text
    r.is_active = True
    r.is_confirmed = False
    r.is_snoozed = False
    r.message_id = None
    return r


# ---------------------------------------------------------------------------
# SNOOZE_OPTIONS
# ---------------------------------------------------------------------------

class TestSnoozeOptions:
    def test_exactly_three_options(self):
        assert len(SNOOZE_OPTIONS) == 3

    def test_default_in_options(self):
        assert DEFAULT_SNOOZE_MINUTES in SNOOZE_OPTIONS


# ---------------------------------------------------------------------------
# cmd_settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_settings_shows_current_snooze():
    msg = _make_message()
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=5))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    assert "5 мин" in msg.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_settings_shows_keyboard():
    msg = _make_message()
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    kb = msg.answer.call_args.kwargs.get("reply_markup")
    assert kb is not None
    assert len(kb.inline_keyboard) == 2  # строка повтора + кнопка timezone


@pytest.mark.asyncio
async def test_cmd_settings_creates_default_when_missing():
    msg = _make_message()
    session = _make_session(settings_obj=None)
    session.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "snooze_minutes", DEFAULT_SNOOZE_MINUTES))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    session.add.assert_called_once()
    session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Клавиатура — отметка текущей опции
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_settings_keyboard_marks_active_snooze_option():
    msg = _make_message()
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=30))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    snooze_texts = [btn.text for btn in msg.answer.call_args.kwargs["reply_markup"].inline_keyboard[0]]
    active = [t for t in snooze_texts if "✅" in t]
    assert len(active) == 1
    assert "30" in active[0]


@pytest.mark.asyncio
async def test_cmd_settings_keyboard_tz_button_collapsed():
    msg = _make_message()
    session = _make_session(settings_obj=_make_user_settings())

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    tz_row = msg.answer.call_args.kwargs["reply_markup"].inline_keyboard[1]
    assert len(tz_row) == 1
    assert tz_row[0].callback_data == "settings:tz_open"


# ---------------------------------------------------------------------------
# Timezone — раскрытие / сворачивание
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_tz_open():
    """Раскрывает все варианты часовых поясов."""
    cb = _make_callback("settings:tz_open")
    cb.message.edit_reply_markup = AsyncMock()
    session = _make_session(settings_obj=_make_user_settings())

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_tz_open(cb)

    kb = cb.message.edit_reply_markup.call_args.kwargs["reply_markup"]
    all_datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    tz_datas = [d for d in all_datas if d and d.startswith("settings:tz:")]
    assert len(tz_datas) == len(TIMEZONE_OPTIONS)
    assert any("Свернуть" in btn.text for row in kb.inline_keyboard for btn in row)


@pytest.mark.asyncio
async def test_handle_tz_close_collapses_keyboard():
    cb = _make_callback("settings:tz_close")
    cb.message.edit_reply_markup = AsyncMock()
    session = _make_session(settings_obj=_make_user_settings())

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_tz_close(cb)

    kb = cb.message.edit_reply_markup.call_args.kwargs["reply_markup"]
    assert len(kb.inline_keyboard) == 2
    assert kb.inline_keyboard[1][0].callback_data == "settings:tz_open"


@pytest.mark.asyncio
async def test_handle_timezone_setting_updates_and_collapses():
    cb = _make_callback("settings:tz:Asia/Yekaterinburg")
    existing = _make_user_settings(snooze_minutes=15, timezone="Europe/Moscow")
    session = _make_session(settings_obj=existing)

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_timezone_setting(cb)

    assert existing.timezone == "Asia/Yekaterinburg"
    kb = cb.message.edit_text.call_args.kwargs["reply_markup"]
    assert len(kb.inline_keyboard) == 2


@pytest.mark.asyncio
async def test_handle_timezone_setting_invalid():
    cb = _make_callback("settings:tz:Invalid/Zone")
    session = _make_session(settings_obj=_make_user_settings())

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_timezone_setting(cb)

    cb.message.edit_text.assert_not_called()
    assert cb.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# handle_snooze_setting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_snooze_setting_updates_and_responds():
    """Обновляет значение, редактирует сообщение с новым текстом и клавиатурой."""
    cb = _make_callback("settings:snooze:5")
    existing = _make_user_settings(snooze_minutes=15)
    session = _make_session(settings_obj=existing)

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_snooze_setting(cb)

    assert existing.snooze_minutes == 5
    session.commit.assert_called_once()
    text = cb.message.edit_text.call_args.args[0]
    assert "5 мин" in text
    snooze_texts = [btn.text for btn in cb.message.edit_text.call_args.kwargs["reply_markup"].inline_keyboard[0]]
    assert any("✅" in t and "5" in t for t in snooze_texts)


@pytest.mark.asyncio
async def test_handle_snooze_setting_invalid_value():
    cb = _make_callback("settings:snooze:99")
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_snooze_setting(cb)

    cb.message.edit_text.assert_not_called()
    assert cb.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# send_reminder — интервал повтора из настроек пользователя
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("snooze_minutes", [5, 30])
async def test_send_reminder_uses_configured_snooze(snooze_minutes):
    from apscheduler.triggers.date import DateTrigger

    reminder = _make_reminder_obj(id=1, user_id=100)
    session = _make_reminder_session(reminder, settings_obj=_make_user_settings(snooze_minutes=snooze_minutes))
    mock_msg = MagicMock()
    mock_msg.message_id = 1
    captured = {}

    mock_scheduler = MagicMock()
    mock_scheduler.add_job.side_effect = lambda f, trigger, **kw: captured.update(trigger=trigger)

    fixed_now = datetime.now()
    with patch("app.services.scheduler.AsyncSessionLocal", return_value=session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler", mock_scheduler), \
         patch("app.services.scheduler._now_tz", side_effect=lambda tz: fixed_now):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(1)

    assert captured["trigger"].run_date.replace(tzinfo=None) == fixed_now + timedelta(minutes=snooze_minutes)


@pytest.mark.asyncio
async def test_send_reminder_fallback_when_no_settings():
    reminder = _make_reminder_obj(id=3, user_id=300)
    session = _make_reminder_session(reminder, settings_obj=None)
    mock_msg = MagicMock()
    mock_msg.message_id = 1
    captured = {}

    mock_scheduler = MagicMock()
    mock_scheduler.add_job.side_effect = lambda f, trigger, **kw: captured.update(trigger=trigger)

    fixed_now = datetime.now()
    with patch("app.services.scheduler.AsyncSessionLocal", return_value=session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler", mock_scheduler), \
         patch("app.services.scheduler.REMINDER_REPEAT_MINUTES", 15), \
         patch("app.services.scheduler._now_tz", side_effect=lambda tz: fixed_now):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(3)

    assert captured["trigger"].run_date.replace(tzinfo=None) == fixed_now + timedelta(minutes=15)