"""
Тесты callback-обработчиков напоминаний (Выполнено / Отложить).

Запуск:
    pytest tests/test_callbacks.py -v
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.reminders import handle_reminder_callback


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_reminder(
    id=1,
    user_id=100,
    text="тест",
    is_active=True,
    is_confirmed=False,
    remind_at=None,
):
    r = MagicMock()
    r.id = id
    r.user_id = user_id
    r.text = text
    r.is_active = is_active
    r.is_confirmed = is_confirmed
    r.remind_at = remind_at or datetime.now() + timedelta(hours=1)
    r.message_id = None
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

        before = datetime.now()
        mock_scheduler = MagicMock()
        mock_scheduler.get_job = MagicMock(return_value=None)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler", mock_scheduler):
            await handle_reminder_callback(cb)

        after = datetime.now()
        assert before + timedelta(minutes=59) <= reminder.remind_at <= after + timedelta(hours=1, minutes=1)

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
