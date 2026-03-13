"""
Тесты on_startup (меню команд) и текстов /start, /help.

Запуск:
    pytest tests/test_main.py -v
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.basic import cmd_start, cmd_help, cmd_privacy, cmd_deleteme
from app.bot.handlers.fallback import unknown_command


EXPECTED_COMMANDS = {"list", "delete", "settings", "cancel", "help", "privacy", "deleteme"}


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
@pytest.mark.parametrize("command", ["/list", "/delete", "/settings", "/cancel", "/privacy", "/deleteme"])
async def test_help_mentions_commands(command):
    msg = _make_message()
    await cmd_help(msg)
    assert command in msg.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# /privacy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_privacy_mentions_deleteme():
    msg = _make_message()
    await cmd_privacy(msg)
    assert "/deleteme" in msg.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# /deleteme
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deleteme_deletes_user_data():
    msg = _make_message()
    msg.from_user.id = 12345

    with patch("app.bot.handlers.basic.AsyncSessionLocal") as mock_session_cls:
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        await cmd_deleteme(msg)

    assert mock_session.execute.call_count == 2
    mock_session.commit.assert_called_once()
    assert "удалены" in msg.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# Fallback — неизвестная команда
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/list", "/settings", "/help"])
async def test_unknown_command_mentions(command):
    msg = _make_message()
    await unknown_command(msg)
    assert command in msg.answer.call_args.args[0]