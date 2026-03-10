"""
Тесты защиты FSM-хендлеров от перехвата команд (/, /cancel, /list и т.д.).

Проблема: хендлеры вида
    @router.message(SomeState, F.text)
перехватывали сообщения-команды до того, как их собственные хендлеры
успевали сработать, и пытались обработать «/cancel» как ввод ID/текста.

Фикс: добавлен фильтр ~F.text.startswith("/") ко всем таким хендлерам.

Запуск:
    pytest tests/test_fsm_guard.py -v
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.reminders import (
    _do_delete,
    handle_delete_id_input,
    handle_edit_text_input,
    handle_edit_time_input,
    handle_reschedule_input,
    handle_time_input,
)


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_message(text: str, user_id: int = 100):
    msg = MagicMock()
    msg.text = text
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.answer = AsyncMock()
    return msg


def _make_state(data: dict | None = None):
    state = AsyncMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value=data or {})
    state.clear = AsyncMock()
    return state


def _make_session(reminder):
    session = AsyncMock()
    session.get = AsyncMock(return_value=reminder)
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=reminder)))
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_reminder(id=1, user_id=100):
    r = MagicMock()
    r.id = id
    r.user_id = user_id
    r.text = "тест"
    r.remind_at = datetime(2026, 6, 1, 10, 0)
    r.is_active = True
    r.is_confirmed = False
    r.is_snoozed = False
    r.recurrence = None
    return r


# ---------------------------------------------------------------------------
# _do_delete: поведение при вводе команды вместо ID
# ---------------------------------------------------------------------------

class TestDoDeleteWithCommandInput:
    """
    Эти тесты проверяют, что _do_delete корректно отклоняет строки-команды.
    После фикса фильтра такие строки вообще не должны доходить до хендлера,
    но тесты служат регрессионной защитой.
    """

    @pytest.mark.asyncio
    async def test_cancel_command_returns_error(self):
        msg = _make_message("/cancel")
        state = _make_state()

        await _do_delete(msg, "/cancel", state)

        msg.answer.assert_called_once()
        assert "❌" in msg.answer.call_args.args[0]
        state.clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_command_returns_error(self):
        msg = _make_message("/list")
        state = _make_state()

        await _do_delete(msg, "/list", state)

        msg.answer.assert_called_once()
        assert "❌" in msg.answer.call_args.args[0]

    @pytest.mark.asyncio
    async def test_arbitrary_command_returns_error(self):
        msg = _make_message("/help")
        state = _make_state()

        await _do_delete(msg, "/help", state)

        assert "❌" in msg.answer.call_args.args[0]

    @pytest.mark.asyncio
    async def test_valid_id_deletes_reminder(self):
        reminder = _make_reminder(id=42)
        msg = _make_message("42")
        state = _make_state()

        with patch("app.bot.handlers.reminders.AsyncSessionLocal", return_value=_make_session(reminder)):
            await _do_delete(msg, "42", state)

        assert reminder.is_active is False
        state.clear.assert_called_once()
        assert "✅" in msg.answer.call_args.args[0]

    @pytest.mark.asyncio
    async def test_garbage_text_returns_error(self):
        msg = _make_message("абвгд")
        state = _make_state()

        await _do_delete(msg, "абвгд", state)

        assert "❌" in msg.answer.call_args.args[0]
        state.clear.assert_not_called()


# ---------------------------------------------------------------------------
# Проверка фильтра ~F.text.startswith("/") у FSM-хендлеров
# ---------------------------------------------------------------------------

class TestFsmHandlersHaveCommandGuard:
    """
    Проверяет, что у FSM-хендлеров, принимающих текстовый ввод,
    установлен фильтр, исключающий команды (startswith "/").
    Если кто-то снимет фильтр — тест упадёт.
    """

    def _collect_filter_strings(self, handler_func) -> list[str]:
        """Возвращает строковые представления фильтров хендлера."""
        filters = getattr(handler_func, "__aiogram_filters__", None)
        if filters is None:
            # aiogram 3 хранит фильтры через __wrapped__ или callback_data
            return []
        return [str(f) for f in filters]

    def _has_command_guard(self, handler_func) -> bool:
        """
        Проверяет наличие фильтра через инспекцию исходного кода хендлера.
        Используем inspect, т.к. aiogram не экспонирует фильтры публично.
        """
        import inspect
        source = inspect.getsource(handler_func)
        return '~F.text.startswith("/")' in source or "startswith" in source

    def test_handle_delete_id_input_has_guard(self):
        assert self._has_command_guard(handle_delete_id_input), (
            "handle_delete_id_input не имеет фильтра ~F.text.startswith('/') — "
            "команды будут перехватываться вместо их собственных хендлеров"
        )

    def test_handle_edit_text_input_has_guard(self):
        assert self._has_command_guard(handle_edit_text_input), (
            "handle_edit_text_input не имеет фильтра ~F.text.startswith('/')"
        )

    def test_handle_edit_time_input_has_guard(self):
        assert self._has_command_guard(handle_edit_time_input), (
            "handle_edit_time_input не имеет фильтра ~F.text.startswith('/')"
        )

    def test_handle_reschedule_input_has_guard(self):
        assert self._has_command_guard(handle_reschedule_input), (
            "handle_reschedule_input не имеет фильтра ~F.text.startswith('/')"
        )

    def test_handle_time_input_has_guard(self):
        assert self._has_command_guard(handle_time_input), (
            "handle_time_input не имеет фильтра ~F.text.startswith('/')"
        )