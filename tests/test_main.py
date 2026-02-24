"""
Тесты on_startup (меню команд) и текстов /start, /help.

Запуск:
    pytest tests/test_main.py -v
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.basic import cmd_start, cmd_help
from app.bot.handlers.fallback import unknown_command


EXPECTED_COMMANDS = {"list", "delete", "settings", "cancel", "help"}


@pytest.fixture
async def startup_commands():
    """Запускает on_startup с замокированными зависимостями и возвращает список команд."""
    from main import on_startup

    with patch("main.init_db", AsyncMock()), \
         patch("main.start_scheduler", MagicMock()), \
         patch("main.load_pending_reminders", AsyncMock()), \
         patch("main.bot") as mock_bot:
        mock_bot.set_my_commands = AsyncMock()
        await on_startup()
        return mock_bot.set_my_commands.call_args.args[0]


def _make_message(first_name: str = "Иван"):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.first_name = first_name
    msg.answer = AsyncMock()
    return msg


# ---------------------------------------------------------------------------
# on_startup — меню команд
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_my_commands_called_once():
    from main import on_startup

    with patch("main.init_db", AsyncMock()), \
         patch("main.start_scheduler", MagicMock()), \
         patch("main.load_pending_reminders", AsyncMock()), \
         patch("main.bot") as mock_bot:
        mock_bot.set_my_commands = AsyncMock()
        await on_startup()

    mock_bot.set_my_commands.assert_called_once()


@pytest.mark.asyncio
async def test_menu_contains_all_expected_commands(startup_commands):
    assert {cmd.command for cmd in startup_commands} == EXPECTED_COMMANDS


@pytest.mark.asyncio
async def test_all_commands_have_description(startup_commands):
    for cmd in startup_commands:
        assert cmd.description, f"Команда /{cmd.command} без описания"


@pytest.mark.asyncio
async def test_no_duplicate_commands(startup_commands):
    names = [cmd.command for cmd in startup_commands]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_greets_user_by_name():
    msg = _make_message(first_name="Мария")
    await cmd_start(msg)
    assert "Мария" in msg.answer.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/list", "/settings", "/help"])
async def test_start_mentions_commands(command):
    msg = _make_message()
    await cmd_start(msg)
    assert command in msg.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/list", "/delete", "/settings", "/cancel"])
async def test_help_mentions_commands(command):
    msg = _make_message()
    await cmd_help(msg)
    assert command in msg.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# Fallback — неизвестная команда
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/list", "/settings", "/help"])
async def test_unknown_command_mentions(command):
    msg = _make_message()
    await unknown_command(msg)
    assert command in msg.answer.call_args.args[0]