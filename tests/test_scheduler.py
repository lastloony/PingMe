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
    def test_layout(self):
        kb = _build_keyboard(42)
        assert len(kb.inline_keyboard) == 2
        assert len(kb.inline_keyboard[0]) == 2
        assert len(kb.inline_keyboard[1]) == 2

    @pytest.mark.parametrize("reminder_id,row,col,expected_data,expected_text", [
        (7, 0, 0, "rem:done:7",        "Выполнено"),
        (7, 0, 1, "rem:snooze:7",      "+1 час"),
        (7, 1, 0, "rem:snooze_day:7",  "+1 день"),
        (7, 1, 1, "rem:reschedule:7",  "Перенести"),
    ])
    def test_buttons(self, reminder_id, row, col, expected_data, expected_text):
        kb = _build_keyboard(reminder_id)
        btn = kb.inline_keyboard[row][col]
        assert btn.callback_data == expected_data
        assert expected_text in btn.text


# ---------------------------------------------------------------------------
# send_reminder
# ---------------------------------------------------------------------------

def _make_reminder(id=1, user_id=100, text="купить хлеб", is_active=True, is_confirmed=False):
    r = MagicMock()
    r.id = id
    r.user_id = user_id
    r.text = text
    r.is_active = is_active
    r.is_confirmed = is_confirmed
    r.is_snoozed = False
    r.message_id = None
    r.recurrence = None
    return r


def _make_session(reminder):
    session = AsyncMock()
    session.get = AsyncMock(return_value=reminder)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize("reminder_obj,label", [
    (_make_reminder(is_confirmed=True), "confirmed"),
    (_make_reminder(is_active=False),   "inactive"),
    (None,                               "not_found"),
])
async def test_send_reminder_skips(reminder_obj, label):
    session = AsyncMock()
    session.get = AsyncMock(return_value=reminder_obj)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=session), \
         patch("app.services.scheduler.bot") as mock_bot:
        await send_reminder(1)
        mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_reminder_sends_with_keyboard():
    reminder = _make_reminder(id=5, user_id=777, text="позвонить маме")
    mock_msg = MagicMock()
    mock_msg.message_id = 999
    session = _make_session(reminder)

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler"):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(5)

    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == 777
    assert "позвонить маме" in call_kwargs["text"]
    assert call_kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_send_reminder_saves_message_id():
    reminder = _make_reminder(id=5)
    mock_msg = MagicMock()
    mock_msg.message_id = 123
    session = _make_session(reminder)

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler"):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(5)

    assert reminder.message_id == 123


@pytest.mark.asyncio
async def test_send_reminder_schedules_repeat_job():
    """Планирует повтор с правильным job ID и временем ~15 мин."""
    from apscheduler.triggers.date import DateTrigger

    reminder = _make_reminder(id=10)
    mock_msg = MagicMock()
    mock_msg.message_id = 1
    session = _make_session(reminder)

    captured = {}

    def capture(func, trigger, **kwargs):
        captured["id"] = kwargs.get("id")
        captured["trigger"] = trigger

    mock_scheduler = MagicMock()
    mock_scheduler.add_job.side_effect = capture

    fixed_now = datetime.now()
    with patch("app.services.scheduler.AsyncSessionLocal", return_value=session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler", mock_scheduler), \
         patch("app.services.scheduler.REMINDER_REPEAT_MINUTES", 15), \
         patch("app.services.scheduler._now_tz", side_effect=lambda tz: fixed_now):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(10)

    assert captured["id"] == "reminder_10"
    assert isinstance(captured["trigger"], DateTrigger)
    assert captured["trigger"].run_date.replace(tzinfo=None) == fixed_now + timedelta(minutes=15)