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


# ---------------------------------------------------------------------------
# set_my_commands вызывается ровно один раз
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


# ---------------------------------------------------------------------------
# Полный набор команд
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_menu_contains_all_expected_commands(startup_commands):
    """Меню содержит все ожидаемые команды."""
    names = {cmd.command for cmd in startup_commands}
    assert EXPECTED_COMMANDS == names


@pytest.mark.asyncio
async def test_menu_contains_list(startup_commands):
    names = {cmd.command for cmd in startup_commands}
    assert "list" in names


@pytest.mark.asyncio
async def test_menu_contains_delete(startup_commands):
    names = {cmd.command for cmd in startup_commands}
    assert "delete" in names


@pytest.mark.asyncio
async def test_menu_contains_settings(startup_commands):
    """/settings присутствует в меню после добавления настроек."""
    names = {cmd.command for cmd in startup_commands}
    assert "settings" in names


@pytest.mark.asyncio
async def test_menu_contains_cancel(startup_commands):
    names = {cmd.command for cmd in startup_commands}
    assert "cancel" in names


@pytest.mark.asyncio
async def test_menu_contains_help(startup_commands):
    names = {cmd.command for cmd in startup_commands}
    assert "help" in names


# ---------------------------------------------------------------------------
# У каждой команды есть непустое описание
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_commands_have_description(startup_commands):
    """У каждой команды есть непустое описание."""
    for cmd in startup_commands:
        assert cmd.description, f"Команда /{cmd.command} без описания"


@pytest.mark.asyncio
async def test_no_duplicate_commands(startup_commands):
    """В меню нет дублирующихся команд."""
    names = [cmd.command for cmd in startup_commands]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Вспомогательная фабрика сообщений
# ---------------------------------------------------------------------------

def _make_message(first_name: str = "Иван"):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.first_name = first_name
    msg.answer = AsyncMock()
    return msg


# ---------------------------------------------------------------------------
# /start — текст содержит нужные команды
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_mentions_list():
    msg = _make_message()
    await cmd_start(msg)
    text = msg.answer.call_args.args[0]
    assert "/list" in text


@pytest.mark.asyncio
async def test_start_mentions_settings():
    """/start упоминает /settings."""
    msg = _make_message()
    await cmd_start(msg)
    text = msg.answer.call_args.args[0]
    assert "/settings" in text


@pytest.mark.asyncio
async def test_start_mentions_help():
    msg = _make_message()
    await cmd_start(msg)
    text = msg.answer.call_args.args[0]
    assert "/help" in text


@pytest.mark.asyncio
async def test_start_greets_user_by_name():
    msg = _make_message(first_name="Мария")
    await cmd_start(msg)
    text = msg.answer.call_args.args[0]
    assert "Мария" in text


# ---------------------------------------------------------------------------
# /help — текст содержит нужные команды
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_help_mentions_list():
    msg = _make_message()
    await cmd_help(msg)
    text = msg.answer.call_args.args[0]
    assert "/list" in text


@pytest.mark.asyncio
async def test_help_mentions_delete():
    msg = _make_message()
    await cmd_help(msg)
    text = msg.answer.call_args.args[0]
    assert "/delete" in text


@pytest.mark.asyncio
async def test_help_mentions_settings():
    """/help упоминает /settings."""
    msg = _make_message()
    await cmd_help(msg)
    text = msg.answer.call_args.args[0]
    assert "/settings" in text


@pytest.mark.asyncio
async def test_help_mentions_cancel():
    msg = _make_message()
    await cmd_help(msg)
    text = msg.answer.call_args.args[0]
    assert "/cancel" in text


# ---------------------------------------------------------------------------
# Fallback — неизвестная команда
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_command_mentions_settings():
    """/settings присутствует в подсказке при неизвестной команде."""
    msg = _make_message()
    await unknown_command(msg)
    text = msg.answer.call_args.args[0]
    assert "/settings" in text


@pytest.mark.asyncio
async def test_unknown_command_mentions_list():
    msg = _make_message()
    await unknown_command(msg)
    text = msg.answer.call_args.args[0]
    assert "/list" in text


@pytest.mark.asyncio
async def test_unknown_command_mentions_help():
    msg = _make_message()
    await unknown_command(msg)
    text = msg.answer.call_args.args[0]
    assert "/help" in text