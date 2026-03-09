"""
Тесты редактирования текста и времени напоминания.

Запуск:
    pytest tests/test_edit.py -v
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.reminders import (
    ReminderStates,
    handle_edit_select,
    handle_edit_text_start,
    handle_edit_text_input,
    handle_edit_time_start,
    handle_edit_time_input,
)


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_reminder(id=1, user_id=100, text="купить хлеб", remind_at=None):
    r = MagicMock()
    r.id = id
    r.user_id = user_id
    r.text = text
    r.remind_at = remind_at or datetime(2026, 6, 1, 10, 0, 0)
    r.is_confirmed = False
    r.is_snoozed = False
    r.message_id = None
    r.recurrence = None
    return r


def _make_callback(data: str, user_id: int = 100):
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.message = MagicMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def _make_message(text: str, user_id: int = 100):
    msg = MagicMock()
    msg.text = text
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.answer = AsyncMock()
    return msg


def _make_session(reminder):
    session = AsyncMock()
    session.get = AsyncMock(return_value=reminder)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_state(data: dict | None = None):
    state = AsyncMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value=data or {})
    state.clear = AsyncMock()
    return state


# ---------------------------------------------------------------------------
# handle_edit_select — показывает кнопки «Текст» / «Время»
# ---------------------------------------------------------------------------

class TestHandleEditSelect:
    @pytest.mark.asyncio
    async def test_shows_text_and_time_buttons(self):
        reminder = _make_reminder(id=5)
        cb = _make_callback("rem:edit:5")

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)):
            await handle_edit_select(cb)

        cb.message.edit_reply_markup.assert_called_once()
        markup = cb.message.edit_reply_markup.call_args.kwargs["reply_markup"]
        all_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "rem:edit_text:5" in all_data
        assert "rem:edit_time:5" in all_data

    @pytest.mark.asyncio
    async def test_wrong_user_rejected(self):
        reminder = _make_reminder(id=5, user_id=100)
        cb = _make_callback("rem:edit:5", user_id=999)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)):
            await handle_edit_select(cb)

        cb.message.edit_reply_markup.assert_not_called()
        assert cb.answer.call_args.kwargs.get("show_alert") is True

    @pytest.mark.asyncio
    async def test_not_found(self):
        session = _make_session(None)
        session.get = AsyncMock(return_value=None)
        cb = _make_callback("rem:edit:99")

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session):
            await handle_edit_select(cb)

        cb.message.edit_reply_markup.assert_not_called()


# ---------------------------------------------------------------------------
# handle_edit_text_start — переход в FSM waiting_for_edit_text
# ---------------------------------------------------------------------------

class TestHandleEditTextStart:
    @pytest.mark.asyncio
    async def test_sets_state_and_shows_prompt(self):
        reminder = _make_reminder(id=7, text="позвонить маме")
        cb = _make_callback("rem:edit_text:7")
        state = _make_state()

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)):
            await handle_edit_text_start(cb, state)

        state.set_state.assert_called_once_with(ReminderStates.waiting_for_edit_text)
        assert state.update_data.call_args.kwargs["reminder_id"] == 7
        cb.message.answer.assert_called_once()
        prompt = cb.message.answer.call_args.args[0]
        assert "позвонить маме" in prompt

    @pytest.mark.asyncio
    async def test_wrong_user_rejected(self):
        reminder = _make_reminder(id=7, user_id=100)
        cb = _make_callback("rem:edit_text:7", user_id=999)
        state = _make_state()

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)):
            await handle_edit_text_start(cb, state)

        state.set_state.assert_not_called()
        cb.message.answer.assert_not_called()


# ---------------------------------------------------------------------------
# handle_edit_text_input — сохранение нового текста
# ---------------------------------------------------------------------------

class TestHandleEditTextInput:
    @pytest.mark.asyncio
    async def test_saves_new_text(self):
        reminder = _make_reminder(id=7, text="старый текст")
        state = _make_state({"reminder_id": 7, "reminder_dt_str": "01.06.2026 10:00"})
        msg = _make_message("новый текст")

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)):
            await handle_edit_text_input(msg, state)

        assert reminder.text == "новый текст"
        state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_replies_with_success(self):
        reminder = _make_reminder(id=7, text="старый")
        state = _make_state({"reminder_id": 7, "reminder_dt_str": "01.06.2026 10:00"})
        msg = _make_message("обновлённый текст")

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)):
            await handle_edit_text_input(msg, state)

        text = msg.answer.call_args.args[0]
        assert "✅" in text and "обновлённый текст" in text

    @pytest.mark.asyncio
    async def test_wrong_user_clears_state(self):
        reminder = _make_reminder(id=7, user_id=100)
        state = _make_state({"reminder_id": 7})
        msg = _make_message("новый текст", user_id=999)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)):
            await handle_edit_text_input(msg, state)

        assert reminder.text != "новый текст"
        state.clear.assert_called_once()
        assert "❌" in msg.answer.call_args.args[0]

    @pytest.mark.asyncio
    async def test_not_found_clears_state(self):
        session = _make_session(None)
        session.get = AsyncMock(return_value=None)
        state = _make_state({"reminder_id": 99})
        msg = _make_message("текст")

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session):
            await handle_edit_text_input(msg, state)

        state.clear.assert_called_once()
        assert "❌" in msg.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# handle_edit_time_start — переход в FSM waiting_for_edit_time
# ---------------------------------------------------------------------------

class TestHandleEditTimeStart:
    @pytest.mark.asyncio
    async def test_sets_state_cancels_job(self):
        remind_at = datetime(2026, 6, 1, 10, 0, 0)
        reminder = _make_reminder(id=8, text="встреча", remind_at=remind_at)
        cb = _make_callback("rem:edit_time:8")
        state = _make_state()
        mock_job = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=mock_job)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler), \
             patch("app.bot.handlers.reminders._load_user_tz", new=AsyncMock(return_value=MagicMock(zone="Europe/Moscow"))):
            await handle_edit_time_start(cb, state)

        mock_job.remove.assert_called_once()
        state.set_state.assert_called_once_with(ReminderStates.waiting_for_edit_time)
        assert state.update_data.call_args.kwargs["reminder_id"] == 8
        cb.message.answer.assert_called_once()
        prompt = cb.message.answer.call_args.args[0]
        assert "встреча" in prompt and "01.06.2026" in prompt

    @pytest.mark.asyncio
    async def test_wrong_user_rejected(self):
        reminder = _make_reminder(id=8, user_id=100)
        cb = _make_callback("rem:edit_time:8", user_id=999)
        state = _make_state()
        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_edit_time_start(cb, state)

        state.set_state.assert_not_called()
        cb.message.answer.assert_not_called()


# ---------------------------------------------------------------------------
# handle_edit_time_input — сохранение нового времени
# ---------------------------------------------------------------------------

class TestHandleEditTimeInput:
    @pytest.mark.asyncio
    async def test_updates_remind_at_and_reschedules(self):
        fixed_now = datetime(2026, 1, 1, 12, 0, 0)
        future_dt = fixed_now + timedelta(hours=5)
        reminder = _make_reminder(id=9)
        state = _make_state({
            "reminder_id": 9,
            "reminder_text": "сходить в зал",
            "tz_name": "Europe/Moscow",
        })
        msg = _make_message("завтра в 10:00")

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)), \
             patch("app.bot.handlers.reminders.dateparser.parse", return_value=future_dt), \
             patch("app.bot.handlers.reminders._now_tz", side_effect=lambda tz: fixed_now), \
             patch("app.bot.handlers.reminders.schedule_reminder") as mock_schedule:
            await handle_edit_time_input(msg, state)

        assert reminder.remind_at == future_dt
        assert reminder.is_snoozed is False
        assert reminder.is_confirmed is False
        assert reminder.message_id is None
        mock_schedule.assert_called_once()
        state.clear.assert_called_once()
        text = msg.answer.call_args.args[0]
        assert "✅" in text and "сходить в зал" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("parsed_dt,label", [
        (None, "unrecognized"),
        ("past", "in the past"),
    ])
    async def test_rejects_invalid_input(self, parsed_dt, label):
        fixed_now = datetime(2026, 1, 1, 12, 0, 0)
        dt = fixed_now - timedelta(hours=1) if parsed_dt == "past" else None
        state = _make_state({"reminder_id": 9, "tz_name": "Europe/Moscow"})
        msg = _make_message("бла")

        with patch("app.bot.handlers.reminders.dateparser.parse", return_value=dt), \
             patch("app.bot.handlers.reminders._now_tz", side_effect=lambda tz: fixed_now):
            await handle_edit_time_input(msg, state)

        assert "❌" in msg.answer.call_args.args[0]
        state.clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_user_clears_state(self):
        fixed_now = datetime(2026, 1, 1, 12, 0, 0)
        future_dt = fixed_now + timedelta(hours=5)
        reminder = _make_reminder(id=9, user_id=100)
        state = _make_state({"reminder_id": 9, "tz_name": "Europe/Moscow", "reminder_text": "тест"})
        msg = _make_message("завтра в 10:00", user_id=999)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)), \
             patch("app.bot.handlers.reminders.dateparser.parse", return_value=future_dt), \
             patch("app.bot.handlers.reminders._now_tz", side_effect=lambda tz: fixed_now), \
             patch("app.bot.handlers.reminders.schedule_reminder") as mock_schedule:
            await handle_edit_time_input(msg, state)

        mock_schedule.assert_not_called()
        state.clear.assert_called_once()
        assert "❌" in msg.answer.call_args.args[0]
