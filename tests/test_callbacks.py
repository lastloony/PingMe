"""
Тесты callback-обработчиков напоминаний (Выполнено / Отложить).

Запуск:
    pytest tests/test_callbacks.py -v
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.reminders import (
    handle_reminder_callback,
    handle_snooze_day,
    handle_reschedule_start,
    handle_reschedule_input,
)


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_reminder(
    id=1,
    user_id=100,
    text="тест",
    is_active=True,
    is_confirmed=False,
    is_snoozed=False,
    remind_at=None,
):
    r = MagicMock()
    r.id = id
    r.user_id = user_id
    r.text = text
    r.is_active = is_active
    r.is_confirmed = is_confirmed
    r.is_snoozed = is_snoozed
    r.remind_at = remind_at or datetime.now() + timedelta(hours=1)
    r.message_id = None
    r.recurrence = None
    return r


def _make_callback(data: str, user_id: int = 100):
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def _make_session(reminder):
    session = AsyncMock()
    session.get = AsyncMock(return_value=reminder)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    # execute() → нет UserSettings → будет использован дефолтный timezone
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)
    return session


# ---------------------------------------------------------------------------
# handle_done
# ---------------------------------------------------------------------------

class TestHandleDone:
    @pytest.mark.asyncio
    async def test_sets_is_confirmed_true(self):
        reminder = _make_reminder(id=1)
        cb = _make_callback("rem:done:1")
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"):
            await handle_reminder_callback(cb)

        assert reminder.is_confirmed is True

    @pytest.mark.asyncio
    async def test_sets_is_active_false(self):
        reminder = _make_reminder(id=1)
        cb = _make_callback("rem:done:1")
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"):
            await handle_reminder_callback(cb)

        assert reminder.is_active is False

    @pytest.mark.asyncio
    async def test_edits_message_with_checkmark(self):
        reminder = _make_reminder(id=1, text="купить хлеб")
        cb = _make_callback("rem:done:1")
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"):
            await handle_reminder_callback(cb)

        cb.message.edit_text.assert_called_once()
        edited_text = cb.message.edit_text.call_args.args[0]
        assert "✅" in edited_text
        assert "Выполнено" in edited_text

    @pytest.mark.asyncio
    async def test_cancels_scheduler_job(self):
        reminder = _make_reminder(id=5)
        cb = _make_callback("rem:done:5")
        session = _make_session(reminder)

        mock_job = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=mock_job)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reminder_callback(cb)

        mock_scheduler.get_job.assert_called_with("reminder_5")
        mock_job.remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_answers_callback(self):
        reminder = _make_reminder(id=1)
        cb = _make_callback("rem:done:1")
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"):
            await handle_reminder_callback(cb)

        cb.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_wrong_user_rejected(self):
        """Другой пользователь не может подтвердить чужое напоминание."""
        reminder = _make_reminder(id=1, user_id=100)
        cb = _make_callback("rem:done:1", user_id=999)
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"):
            await handle_reminder_callback(cb)

        # Сообщение не редактируется
        cb.message.edit_text.assert_not_called()
        # is_confirmed не меняется
        assert reminder.is_confirmed is False


# ---------------------------------------------------------------------------
# handle_snooze
# ---------------------------------------------------------------------------

class TestHandleSnooze:
    @pytest.mark.asyncio
    async def test_remind_at_shifted_by_one_hour(self):
        reminder = _make_reminder(id=2)
        cb = _make_callback("rem:snooze:2")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        fixed_now = datetime.now()
        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler), \
             patch("app.bot.handlers.reminders._now_tz", side_effect=lambda tz: fixed_now):
            await handle_reminder_callback(cb)

        assert reminder.remind_at == fixed_now + timedelta(hours=1)

    @pytest.mark.asyncio
    async def test_is_snoozed_set_on_snooze(self):
        reminder = _make_reminder(id=2, is_snoozed=False)
        cb = _make_callback("rem:snooze:2")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reminder_callback(cb)

        assert reminder.is_snoozed is True

    @pytest.mark.asyncio
    async def test_is_confirmed_reset(self):
        reminder = _make_reminder(id=2, is_confirmed=True)
        cb = _make_callback("rem:snooze:2")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reminder_callback(cb)

        assert reminder.is_confirmed is False

    @pytest.mark.asyncio
    async def test_edits_message_with_clock(self):
        reminder = _make_reminder(id=2, text="встреча")
        cb = _make_callback("rem:snooze:2")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reminder_callback(cb)

        cb.message.edit_text.assert_called_once()
        edited_text = cb.message.edit_text.call_args.args[0]
        assert "⏱" in edited_text
        assert "Отложено" in edited_text

    @pytest.mark.asyncio
    async def test_schedules_new_job(self):
        reminder = _make_reminder(id=3)
        cb = _make_callback("rem:snooze:3")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reminder_callback(cb)

        mock_scheduler.add_job.assert_called_once()
        call_kwargs = mock_scheduler.add_job.call_args
        assert call_kwargs.kwargs["id"] == "reminder_3"

    @pytest.mark.asyncio
    async def test_cancels_old_job(self):
        reminder = _make_reminder(id=3)
        cb = _make_callback("rem:snooze:3")
        session = _make_session(reminder)

        mock_job = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=mock_job)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reminder_callback(cb)

        mock_job.remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_message_id_reset_on_snooze(self):
        """После snooze message_id сбрасывается, чтобы /list не показывал метку «Отложено»."""
        reminder = _make_reminder(id=2)
        reminder.message_id = 42
        cb = _make_callback("rem:snooze:2")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reminder_callback(cb)

        assert reminder.message_id is None

    @pytest.mark.asyncio
    async def test_answers_callback(self):
        reminder = _make_reminder(id=2)
        cb = _make_callback("rem:snooze:2")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reminder_callback(cb)

        cb.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_wrong_user_rejected(self):
        reminder = _make_reminder(id=2, user_id=100)
        cb = _make_callback("rem:snooze:2", user_id=777)
        session = _make_session(reminder)

        mock_scheduler = MagicMock()

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reminder_callback(cb)

        cb.message.edit_text.assert_not_called()
        mock_scheduler.add_job.assert_not_called()


# ---------------------------------------------------------------------------
# Граничные случаи
# ---------------------------------------------------------------------------

class TestCallbackEdgeCases:
    @pytest.mark.asyncio
    async def test_reminder_not_found(self):
        cb = _make_callback("rem:done:999")
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"):
            await handle_reminder_callback(cb)

        cb.message.edit_text.assert_not_called()
        cb.answer.assert_called_once()
        # Должен сообщить об ошибке
        assert cb.answer.call_args.kwargs.get("show_alert") is True

    @pytest.mark.asyncio
    async def test_done_preserves_reminder_text_in_edit(self):
        reminder = _make_reminder(id=1, text="позвонить другу")
        cb = _make_callback("rem:done:1")
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"):
            await handle_reminder_callback(cb)

        edited_text = cb.message.edit_text.call_args.args[0]
        assert "позвонить другу" in edited_text

    @pytest.mark.asyncio
    async def test_snooze_preserves_reminder_text_in_edit(self):
        reminder = _make_reminder(id=2, text="выпить таблетку")
        cb = _make_callback("rem:snooze:2")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reminder_callback(cb)

        edited_text = cb.message.edit_text.call_args.args[0]
        assert "выпить таблетку" in edited_text


# ---------------------------------------------------------------------------
# handle_snooze_day (+1 день)
# ---------------------------------------------------------------------------

class TestHandleSnoozeDay:
    @pytest.mark.asyncio
    async def test_remind_at_shifted_by_one_day(self):
        original = datetime.now() + timedelta(hours=2)
        reminder = _make_reminder(id=10, remind_at=original)
        cb = _make_callback("rem:snooze_day:10")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_snooze_day(cb)

        assert reminder.remind_at == original + timedelta(days=1)

    @pytest.mark.asyncio
    async def test_fallback_to_now_plus_day_if_past(self):
        """Если remind_at + 1 день всё равно в прошлом — берём _now + 1 день."""
        past = datetime.now() - timedelta(days=2)
        reminder = _make_reminder(id=10, remind_at=past)
        cb = _make_callback("rem:snooze_day:10")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        fixed_now = datetime.now()
        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler), \
             patch("app.bot.handlers.reminders._now_tz", side_effect=lambda tz: fixed_now):
            await handle_snooze_day(cb)

        assert reminder.remind_at == fixed_now + timedelta(days=1)

    @pytest.mark.asyncio
    async def test_sets_is_snoozed(self):
        reminder = _make_reminder(id=10)
        cb = _make_callback("rem:snooze_day:10")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_snooze_day(cb)

        assert reminder.is_snoozed is True

    @pytest.mark.asyncio
    async def test_message_id_reset(self):
        reminder = _make_reminder(id=10)
        reminder.message_id = 77
        cb = _make_callback("rem:snooze_day:10")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_snooze_day(cb)

        assert reminder.message_id is None

    @pytest.mark.asyncio
    async def test_schedules_new_job(self):
        reminder = _make_reminder(id=10)
        cb = _make_callback("rem:snooze_day:10")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_snooze_day(cb)

        mock_scheduler.add_job.assert_called_once()
        assert mock_scheduler.add_job.call_args.kwargs["id"] == "reminder_10"

    @pytest.mark.asyncio
    async def test_edits_message_with_date(self):
        reminder = _make_reminder(id=10, text="купить молоко")
        cb = _make_callback("rem:snooze_day:10")
        session = _make_session(reminder)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_snooze_day(cb)

        cb.message.edit_text.assert_called_once()
        text = cb.message.edit_text.call_args.args[0]
        assert "📅" in text
        assert "Перенесено" in text
        assert "купить молоко" in text

    @pytest.mark.asyncio
    async def test_wrong_user_rejected(self):
        reminder = _make_reminder(id=10, user_id=100)
        cb = _make_callback("rem:snooze_day:10", user_id=999)
        session = _make_session(reminder)

        mock_scheduler = MagicMock()

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_snooze_day(cb)

        cb.message.edit_text.assert_not_called()
        mock_scheduler.add_job.assert_not_called()


# ---------------------------------------------------------------------------
# handle_reschedule_start (✏️ Перенести)
# ---------------------------------------------------------------------------

class TestHandleRescheduleStart:
    def _make_state(self):
        state = AsyncMock()
        state.set_state = AsyncMock()
        state.update_data = AsyncMock()
        return state

    @pytest.mark.asyncio
    async def test_sets_fsm_state(self):
        from app.bot.handlers.reminders import ReminderStates
        reminder = _make_reminder(id=20)
        cb = _make_callback("rem:reschedule:20")
        session = _make_session(reminder)
        state = self._make_state()

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reschedule_start(cb, state)

        state.set_state.assert_called_once_with(ReminderStates.waiting_for_reschedule)

    @pytest.mark.asyncio
    async def test_saves_reminder_id_in_state(self):
        reminder = _make_reminder(id=20)
        cb = _make_callback("rem:reschedule:20")
        session = _make_session(reminder)
        state = self._make_state()

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reschedule_start(cb, state)

        call_kwargs = state.update_data.call_args.kwargs
        assert call_kwargs["reminder_id"] == 20

    @pytest.mark.asyncio
    async def test_cancels_existing_job(self):
        reminder = _make_reminder(id=20)
        cb = _make_callback("rem:reschedule:20")
        session = _make_session(reminder)
        state = self._make_state()

        mock_job = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=mock_job)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reschedule_start(cb, state)

        mock_job.remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_edits_message_with_prompt(self):
        reminder = _make_reminder(id=20, text="позвонить другу")
        cb = _make_callback("rem:reschedule:20")
        session = _make_session(reminder)
        state = self._make_state()

        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reschedule_start(cb, state)

        cb.message.edit_text.assert_called_once()
        text = cb.message.edit_text.call_args.args[0]
        assert "✏️" in text
        assert "позвонить другу" in text

    @pytest.mark.asyncio
    async def test_wrong_user_rejected(self):
        reminder = _make_reminder(id=20, user_id=100)
        cb = _make_callback("rem:reschedule:20", user_id=999)
        session = _make_session(reminder)
        state = self._make_state()

        mock_scheduler = MagicMock()

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reschedule_start(cb, state)

        state.set_state.assert_not_called()
        cb.message.edit_text.assert_not_called()


# ---------------------------------------------------------------------------
# handle_reschedule_input (FSM — ввод нового времени)
# ---------------------------------------------------------------------------

class TestHandleRescheduleInput:
    def _make_state(self, reminder_id=30, reminder_text="тест"):
        state = AsyncMock()
        state.get_data = AsyncMock(return_value={
            "reminder_id": reminder_id,
            "reminder_text": reminder_text,
        })
        state.clear = AsyncMock()
        return state

    def _make_message(self, text: str, user_id: int = 100):
        msg = MagicMock()
        msg.text = text
        msg.from_user = MagicMock()
        msg.from_user.id = user_id
        msg.answer = AsyncMock()
        return msg

    @pytest.mark.asyncio
    async def test_reschedules_with_valid_input(self):
        fixed_now = datetime(2026, 1, 1, 12, 0, 0)
        future_dt = fixed_now + timedelta(hours=3)
        reminder = _make_reminder(id=30)
        session = _make_session(reminder)
        state = self._make_state(reminder_id=30)
        msg = self._make_message("завтра в 10:00")

        mock_scheduler = MagicMock()

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler), \
             patch("app.bot.handlers.reminders.dateparser.parse", return_value=future_dt), \
             patch("app.bot.handlers.reminders._now_tz", side_effect=lambda tz: fixed_now):
            await handle_reschedule_input(msg, state)

        assert reminder.remind_at == future_dt
        mock_scheduler.add_job.assert_called_once()
        state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_past_time(self):
        fixed_now = datetime(2026, 1, 1, 12, 0, 0)
        past_dt = fixed_now - timedelta(hours=1)
        state = self._make_state()
        msg = self._make_message("вчера")

        with patch("app.bot.handlers.reminders.dateparser.parse", return_value=past_dt), \
             patch("app.bot.handlers.reminders._now_tz", side_effect=lambda tz: fixed_now):
            await handle_reschedule_input(msg, state)

        msg.answer.assert_called_once()
        assert "❌" in msg.answer.call_args.args[0]
        state.clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_unrecognized_input(self):
        fixed_now = datetime(2026, 1, 1, 12, 0, 0)
        state = self._make_state()
        msg = self._make_message("бла бла")

        with patch("app.bot.handlers.reminders.dateparser.parse", return_value=None), \
             patch("app.bot.handlers.reminders._now_tz", side_effect=lambda tz: fixed_now):
            await handle_reschedule_input(msg, state)

        msg.answer.assert_called_once()
        assert "❌" in msg.answer.call_args.args[0]
        state.clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirms_reschedule_to_user(self):
        future_dt = datetime.now() + timedelta(days=1)
        reminder = _make_reminder(id=30)
        session = _make_session(reminder)
        state = self._make_state(reminder_id=30, reminder_text="встреча")
        msg = self._make_message("завтра в 12:00")

        mock_scheduler = MagicMock()

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler), \
             patch("app.bot.handlers.reminders.dateparser.parse", return_value=future_dt), \
             patch("app.bot.handlers.reminders._now_tz", side_effect=lambda tz: datetime.now()):
            await handle_reschedule_input(msg, state)

        msg.answer.assert_called_once()
        text = msg.answer.call_args.args[0]
        assert "✅" in text
        assert "встреча" in text
