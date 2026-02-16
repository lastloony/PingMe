"""
Тесты планировщика напоминаний (send_reminder).

Запуск:
    pytest tests/test_scheduler.py -v
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.scheduler import _build_keyboard, send_reminder


# ---------------------------------------------------------------------------
# _build_keyboard
# ---------------------------------------------------------------------------

class TestBuildKeyboard:
    def test_has_two_buttons(self):
        kb = _build_keyboard(42)
        buttons = kb.inline_keyboard[0]
        assert len(buttons) == 2

    def test_done_callback(self):
        kb = _build_keyboard(7)
        done_btn = kb.inline_keyboard[0][0]
        assert done_btn.callback_data == "rem:done:7"
        assert "Выполнено" in done_btn.text

    def test_snooze_callback(self):
        kb = _build_keyboard(7)
        snooze_btn = kb.inline_keyboard[0][1]
        assert snooze_btn.callback_data == "rem:snooze:7"
        assert "Отложить" in snooze_btn.text

    def test_different_ids(self):
        kb1 = _build_keyboard(1)
        kb2 = _build_keyboard(99)
        assert "1" in kb1.inline_keyboard[0][0].callback_data
        assert "99" in kb2.inline_keyboard[0][0].callback_data


# ---------------------------------------------------------------------------
# send_reminder
# ---------------------------------------------------------------------------

def _make_reminder(
    id=1,
    user_id=100,
    text="купить хлеб",
    is_active=True,
    is_confirmed=False,
):
    r = MagicMock()
    r.id = id
    r.user_id = user_id
    r.text = text
    r.is_active = is_active
    r.is_confirmed = is_confirmed
    r.message_id = None
    return r


@pytest.mark.asyncio
async def test_send_reminder_skips_confirmed():
    """Не отправляет если is_confirmed=True."""
    reminder = _make_reminder(is_confirmed=True)

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=reminder)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=mock_session), \
         patch("app.services.scheduler.bot") as mock_bot:
        await send_reminder(1)
        mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_reminder_skips_inactive():
    """Не отправляет если is_active=False."""
    reminder = _make_reminder(is_active=False)

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=reminder)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=mock_session), \
         patch("app.services.scheduler.bot") as mock_bot:
        await send_reminder(1)
        mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_reminder_skips_missing():
    """Не падает если напоминание не найдено в БД."""
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=mock_session), \
         patch("app.services.scheduler.bot") as mock_bot:
        await send_reminder(999)
        mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_reminder_sends_with_keyboard():
    """Отправляет сообщение с inline-клавиатурой."""
    reminder = _make_reminder(id=5, user_id=777, text="позвонить маме")

    mock_msg = MagicMock()
    mock_msg.message_id = 999

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=reminder)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_scheduler = MagicMock()

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=mock_session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler", mock_scheduler):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(5)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args
    assert call_kwargs.kwargs["chat_id"] == 777
    assert "позвонить маме" in call_kwargs.kwargs["text"]
    assert call_kwargs.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_send_reminder_saves_message_id():
    """Сохраняет message_id в напоминании."""
    reminder = _make_reminder(id=5)

    mock_msg = MagicMock()
    mock_msg.message_id = 123

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=reminder)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_scheduler = MagicMock()

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=mock_session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler", mock_scheduler):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(5)

    assert reminder.message_id == 123


@pytest.mark.asyncio
async def test_send_reminder_schedules_repeat():
    """Планирует повтор через 15 минут после отправки."""
    reminder = _make_reminder(id=10)

    mock_msg = MagicMock()
    mock_msg.message_id = 1

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=reminder)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_scheduler = MagicMock()

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=mock_session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler", mock_scheduler):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(10)

    mock_scheduler.add_job.assert_called_once()
    call_kwargs = mock_scheduler.add_job.call_args
    assert call_kwargs.kwargs.get("id") == "reminder_10" or call_kwargs.args[0] is not None


@pytest.mark.asyncio
async def test_send_reminder_repeat_job_id():
    """Job повтора имеет правильный ID (reminder_<id>)."""
    reminder = _make_reminder(id=42)

    mock_msg = MagicMock()
    mock_msg.message_id = 1

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=reminder)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_scheduler = MagicMock()

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=mock_session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler", mock_scheduler):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(42)

    call_kwargs = mock_scheduler.add_job.call_args
    assert call_kwargs.kwargs["id"] == "reminder_42"


@pytest.mark.asyncio
async def test_send_reminder_repeat_within_15_minutes():
    """Повтор запланирован примерно через 15 минут."""
    from apscheduler.triggers.date import DateTrigger

    reminder = _make_reminder(id=3)

    mock_msg = MagicMock()
    mock_msg.message_id = 1

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=reminder)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    captured_trigger = {}

    def capture_add_job(func, trigger, **kwargs):
        captured_trigger["trigger"] = trigger

    mock_scheduler = MagicMock()
    mock_scheduler.add_job.side_effect = capture_add_job

    fixed_now = datetime.now()
    with patch("app.services.scheduler.AsyncSessionLocal", return_value=mock_session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler", mock_scheduler), \
         patch("app.services.scheduler.REMINDER_REPEAT_MINUTES", 15), \
         patch("app.services.scheduler._now", return_value=fixed_now):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(3)

    trigger = captured_trigger["trigger"]
    assert isinstance(trigger, DateTrigger)
    run_date = trigger.run_date.replace(tzinfo=None)
    assert run_date == fixed_now + timedelta(minutes=15)
