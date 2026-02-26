"""
Тесты периодических напоминаний: _next_occurrence, _extract_recurrence,
поведение handle_reminder_callback при action=done для recurrence-напоминаний.

Запуск:
    pytest tests/test_recurrence.py -v
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.scheduler import _next_occurrence
from app.bot.handlers.reminders import _extract_recurrence, handle_reminder_callback


# ---------------------------------------------------------------------------
# _next_occurrence
# ---------------------------------------------------------------------------

class TestNextOccurrence:
    BASE = datetime(2026, 3, 15, 10, 0)

    def test_hourly(self):
        assert _next_occurrence(self.BASE, "hourly") == datetime(2026, 3, 15, 11, 0)

    def test_daily(self):
        assert _next_occurrence(self.BASE, "daily") == datetime(2026, 3, 16, 10, 0)

    def test_weekly(self):
        assert _next_occurrence(self.BASE, "weekly") == datetime(2026, 3, 22, 10, 0)

    def test_monthly(self):
        assert _next_occurrence(self.BASE, "monthly") == datetime(2026, 4, 15, 10, 0)

    def test_monthly_end_of_month(self):
        # 31 января → 28 февраля (не выходит за границу месяца)
        dt = datetime(2026, 1, 31, 10, 0)
        result = _next_occurrence(dt, "monthly")
        assert result == datetime(2026, 2, 28, 10, 0)

    def test_yearly(self):
        assert _next_occurrence(self.BASE, "yearly") == datetime(2027, 3, 15, 10, 0)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown recurrence"):
            _next_occurrence(self.BASE, "biweekly")


# ---------------------------------------------------------------------------
# _extract_recurrence
# ---------------------------------------------------------------------------

class TestExtractRecurrence:
    @pytest.mark.parametrize("text,expected", [
        ("проверять сервер каждый час",          "hourly"),
        ("тест раз в час",                       "hourly"),
        ("зарядка каждый день в 7:00",           "daily"),
        ("тест раз в день",                      "daily"),
        ("тест раз в сутки",                     "daily"),
        ("отчёт в 18:00 еженедельно",            "weekly"),
        ("тест раз в неделю",                    "weekly"),
        ("оплата каждый месяц 1 числа",          "monthly"),
        ("тест раз в месяц",                     "monthly"),
        ("заплатить налог 20 ноября ежегодно",   "yearly"),
        ("тест раз в год",                       "yearly"),
    ])
    def test_patterns(self, text, expected):
        _, rec = _extract_recurrence(text)
        assert rec == expected

    def test_no_recurrence(self):
        text, rec = _extract_recurrence("позвонить маме завтра в 10:00")
        assert rec is None
        assert text == "позвонить маме завтра в 10:00"

    def test_keyword_removed_from_text(self):
        text, rec = _extract_recurrence("выпить кофе ежедневно")
        assert rec == "daily"
        assert text.strip() == "выпить кофе"


# ---------------------------------------------------------------------------
# handle_reminder_callback — done с recurrence
# ---------------------------------------------------------------------------

def _make_reminder_recurring(
    id=1, user_id=100, recurrence="daily",
    remind_at=None, recurrence_anchor=None,
):
    anchor = recurrence_anchor or datetime(2026, 3, 15, 8, 0)
    r = MagicMock()
    r.id = id
    r.user_id = user_id
    r.text = "выпить кофе"
    r.is_active = True
    r.is_confirmed = False
    r.is_snoozed = False
    r.message_id = None
    r.recurrence = recurrence
    r.recurrence_anchor = anchor
    r.remind_at = remind_at or anchor
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


def _make_callback(data: str, user_id: int = 100):
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    return cb


class TestHandleDoneRecurring:
    @pytest.mark.asyncio
    async def test_stays_active(self):
        """Периодическое напоминание остаётся активным после Выполнено."""
        reminder = _make_reminder_recurring(id=1)
        cb = _make_callback("rem:done:1")
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"), \
             patch("app.bot.handlers.reminders.schedule_reminder"):
            await handle_reminder_callback(cb)

        assert reminder.is_active is True
        assert reminder.is_confirmed is False

    @pytest.mark.asyncio
    async def test_remind_at_advanced_by_one_day(self):
        """remind_at сдвигается на 1 день для daily."""
        anchor = datetime(2026, 3, 15, 8, 0)
        reminder = _make_reminder_recurring(id=1, recurrence="daily", recurrence_anchor=anchor)
        cb = _make_callback("rem:done:1")
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"), \
             patch("app.bot.handlers.reminders.schedule_reminder"):
            await handle_reminder_callback(cb)

        assert reminder.remind_at == anchor + timedelta(days=1)

    @pytest.mark.asyncio
    async def test_anchor_updated(self):
        """recurrence_anchor обновляется вместе с remind_at."""
        anchor = datetime(2026, 3, 15, 8, 0)
        reminder = _make_reminder_recurring(id=1, recurrence="daily", recurrence_anchor=anchor)
        cb = _make_callback("rem:done:1")
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"), \
             patch("app.bot.handlers.reminders.schedule_reminder"):
            await handle_reminder_callback(cb)

        assert reminder.recurrence_anchor == anchor + timedelta(days=1)

    @pytest.mark.asyncio
    async def test_uses_anchor_not_remind_at(self):
        """Если remind_at смещён (Перенести), next считается от anchor."""
        anchor = datetime(2026, 3, 15, 8, 0)
        shifted = datetime(2026, 3, 16, 15, 0)  # пользователь перенёс на другое время
        reminder = _make_reminder_recurring(
            id=1, recurrence="monthly",
            recurrence_anchor=anchor, remind_at=shifted,
        )
        cb = _make_callback("rem:done:1")
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"), \
             patch("app.bot.handlers.reminders.schedule_reminder"):
            await handle_reminder_callback(cb)

        # Следующий срок — от anchor (15 марта), а не от shifted (16 марта)
        from dateutil.relativedelta import relativedelta
        expected = anchor + relativedelta(months=1)
        assert reminder.remind_at == expected

    @pytest.mark.asyncio
    async def test_message_contains_next_date(self):
        """Сообщение после Выполнено содержит дату следующего срабатывания."""
        anchor = datetime(2026, 3, 15, 8, 0)
        reminder = _make_reminder_recurring(id=1, recurrence="daily", recurrence_anchor=anchor)
        cb = _make_callback("rem:done:1")
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"), \
             patch("app.bot.handlers.reminders.schedule_reminder"):
            await handle_reminder_callback(cb)

        edited = cb.message.edit_text.call_args.args[0]
        assert "Следующее" in edited
        assert "16.03.2026" in edited

    @pytest.mark.asyncio
    async def test_schedule_reminder_called(self):
        """schedule_reminder вызывается для планирования следующего срока."""
        reminder = _make_reminder_recurring(id=1, recurrence="daily")
        cb = _make_callback("rem:done:1")
        session = _make_session(reminder)

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=session), \
             patch("app.bot.handlers.reminders.scheduler"), \
             patch("app.bot.handlers.reminders.schedule_reminder") as mock_schedule:
            await handle_reminder_callback(cb)

        mock_schedule.assert_called_once()