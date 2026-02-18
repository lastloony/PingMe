"""
Тесты хендлера настроек пользователя и интеграции с планировщиком.

Запуск:
    pytest tests/test_settings.py -v
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.settings import (
    cmd_settings,
    handle_snooze_setting,
    handle_tz_open,
    handle_tz_close,
    handle_timezone_setting,
    SNOOZE_OPTIONS,
    TIMEZONE_OPTIONS,
)
from app.database import DEFAULT_SNOOZE_MINUTES
from app.services.scheduler import send_reminder


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_message(user_id: int = 42):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.answer = AsyncMock()
    return msg


def _make_callback(data: str, user_id: int = 42):
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def _make_user_settings(snooze_minutes: int = DEFAULT_SNOOZE_MINUTES, timezone: str = "Europe/Moscow"):
    obj = MagicMock()
    obj.snooze_minutes = snooze_minutes
    obj.timezone = timezone
    return obj


def _make_session(settings_obj=None):
    """Создаёт мок сессии с настройками пользователя."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = settings_obj
    session.execute = AsyncMock(return_value=mock_result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_reminder_session(reminder, settings_obj=None):
    """Сессия для send_reminder: get() → reminder, execute() → settings."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=reminder)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = settings_obj
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_reminder_obj(id=1, user_id=100, text="тест"):
    r = MagicMock()
    r.id = id
    r.user_id = user_id
    r.text = text
    r.is_active = True
    r.is_confirmed = False
    r.is_snoozed = False
    r.message_id = None
    return r


# ---------------------------------------------------------------------------
# SNOOZE_OPTIONS
# ---------------------------------------------------------------------------

class TestSnoozeOptions:
    def test_contains_5(self):
        assert 5 in SNOOZE_OPTIONS

    def test_contains_15(self):
        assert 15 in SNOOZE_OPTIONS

    def test_contains_30(self):
        assert 30 in SNOOZE_OPTIONS

    def test_exactly_three_options(self):
        assert len(SNOOZE_OPTIONS) == 3

    def test_default_in_options(self):
        assert DEFAULT_SNOOZE_MINUTES in SNOOZE_OPTIONS


# ---------------------------------------------------------------------------
# cmd_settings — существующие настройки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_settings_shows_current_snooze():
    """/settings показывает текущий интервал из БД."""
    msg = _make_message()
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=5))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    msg.answer.assert_called_once()
    text = msg.answer.call_args.args[0]
    assert "5 мин" in text


@pytest.mark.asyncio
async def test_cmd_settings_shows_keyboard():
    """/settings возвращает inline-клавиатуру с 2 строками (свёрнутый вид)."""
    msg = _make_message()
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    kb = msg.answer.call_args.kwargs.get("reply_markup")
    assert kb is not None
    assert len(kb.inline_keyboard) == 2  # строка повтора + кнопка timezone


# ---------------------------------------------------------------------------
# cmd_settings — настроек ещё нет (создаёт дефолтные)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_settings_creates_default_when_missing():
    """/settings создаёт запись с дефолтом 15 мин, если её нет."""
    msg = _make_message()
    session = _make_session(settings_obj=None)

    created = _make_user_settings(snooze_minutes=DEFAULT_SNOOZE_MINUTES)
    session.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "snooze_minutes", DEFAULT_SNOOZE_MINUTES))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    session.add.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_settings_default_snooze_in_text():
    """/settings показывает дефолтный интервал в тексте при создании."""
    msg = _make_message()

    # После refresh у объекта будет snooze_minutes = DEFAULT_SNOOZE_MINUTES
    new_obj = _make_user_settings(snooze_minutes=DEFAULT_SNOOZE_MINUTES)

    async def fake_refresh(obj):
        obj.snooze_minutes = DEFAULT_SNOOZE_MINUTES

    session = _make_session(settings_obj=None)
    session.refresh = AsyncMock(side_effect=fake_refresh)

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    text = msg.answer.call_args.args[0]
    assert str(DEFAULT_SNOOZE_MINUTES) in text


# ---------------------------------------------------------------------------
# Клавиатура — отметка текущей опции
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_settings_keyboard_marks_active_snooze_option():
    """Текущая опция повтора отмечена галочкой ✅."""
    msg = _make_message()
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=30))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    # Первая строка клавиатуры — кнопки повтора
    keyboard = msg.answer.call_args.kwargs["reply_markup"]
    snooze_texts = [btn.text for btn in keyboard.inline_keyboard[0]]
    active = [t for t in snooze_texts if "✅" in t]
    assert len(active) == 1
    assert "30" in active[0]


@pytest.mark.asyncio
async def test_cmd_settings_keyboard_inactive_snooze_options_no_checkmark():
    """Неактивные опции повтора не содержат галочку."""
    msg = _make_message()
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    keyboard = msg.answer.call_args.kwargs["reply_markup"]
    snooze_texts = [btn.text for btn in keyboard.inline_keyboard[0]]
    inactive = [t for t in snooze_texts if "✅" not in t]
    assert len(inactive) == 2


@pytest.mark.asyncio
async def test_cmd_settings_keyboard_tz_button_collapsed():
    """В свёрнутом виде вторая строка — одна кнопка с callback settings:tz_open."""
    msg = _make_message()
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await cmd_settings(msg)

    kb = msg.answer.call_args.kwargs["reply_markup"]
    tz_row = kb.inline_keyboard[1]
    assert len(tz_row) == 1
    assert tz_row[0].callback_data == "settings:tz_open"


@pytest.mark.asyncio
async def test_handle_tz_open_expands_keyboard():
    """handle_tz_open раскрывает все кнопки часовых поясов."""
    cb = _make_callback("settings:tz_open")
    cb.message.edit_reply_markup = AsyncMock()
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_tz_open(cb)

    cb.message.edit_reply_markup.assert_called_once()
    kb = cb.message.edit_reply_markup.call_args.kwargs["reply_markup"]
    all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("UTC" in t for t in all_texts)
    assert any("Свернуть" in t for t in all_texts)
    assert len(kb.inline_keyboard) > 2  # snooze + tz-строки + свернуть


@pytest.mark.asyncio
async def test_handle_tz_open_shows_all_tz_options():
    """В раскрытом виде присутствуют все варианты часовых поясов."""
    cb = _make_callback("settings:tz_open")
    cb.message.edit_reply_markup = AsyncMock()
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_tz_open(cb)

    kb = cb.message.edit_reply_markup.call_args.kwargs["reply_markup"]
    all_datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    tz_datas = [d for d in all_datas if d and d.startswith("settings:tz:")]
    assert len(tz_datas) == len(TIMEZONE_OPTIONS)


@pytest.mark.asyncio
async def test_handle_tz_close_collapses_keyboard():
    """handle_tz_close сворачивает клавиатуру обратно к 2 строкам."""
    cb = _make_callback("settings:tz_close")
    cb.message.edit_reply_markup = AsyncMock()
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_tz_close(cb)

    kb = cb.message.edit_reply_markup.call_args.kwargs["reply_markup"]
    assert len(kb.inline_keyboard) == 2
    assert kb.inline_keyboard[1][0].callback_data == "settings:tz_open"


@pytest.mark.asyncio
async def test_handle_timezone_setting_updates_and_collapses():
    """После выбора часового пояса клавиатура сворачивается (2 строки)."""
    cb = _make_callback("settings:tz:Asia/Yekaterinburg")
    existing = _make_user_settings(snooze_minutes=15, timezone="Europe/Moscow")
    session = _make_session(settings_obj=existing)

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_timezone_setting(cb)

    assert existing.timezone == "Asia/Yekaterinburg"
    kb = cb.message.edit_text.call_args.kwargs["reply_markup"]
    assert len(kb.inline_keyboard) == 2
    assert kb.inline_keyboard[1][0].callback_data == "settings:tz_open"


@pytest.mark.asyncio
async def test_handle_timezone_setting_invalid():
    """Недопустимый часовой пояс отклоняется с show_alert."""
    cb = _make_callback("settings:tz:Invalid/Zone")
    session = _make_session(settings_obj=_make_user_settings())

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_timezone_setting(cb)

    cb.message.edit_text.assert_not_called()
    assert cb.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# handle_snooze_setting — обновление значения
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_snooze_setting_updates_value():
    """Callback обновляет snooze_minutes в объекте настроек."""
    cb = _make_callback("settings:snooze:5")
    existing = _make_user_settings(snooze_minutes=15)
    session = _make_session(settings_obj=existing)

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_snooze_setting(cb)

    assert existing.snooze_minutes == 5
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_handle_snooze_setting_edits_message():
    """Callback редактирует сообщение с новым значением."""
    cb = _make_callback("settings:snooze:30")
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_snooze_setting(cb)

    cb.message.edit_text.assert_called_once()
    text = cb.message.edit_text.call_args.args[0]
    assert "30 мин" in text


@pytest.mark.asyncio
async def test_handle_snooze_setting_answers_confirmation():
    """Callback отвечает с подтверждением нового интервала."""
    cb = _make_callback("settings:snooze:5")
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_snooze_setting(cb)

    cb.answer.assert_called_once()
    answer_text = cb.answer.call_args.args[0]
    assert "5" in answer_text


@pytest.mark.asyncio
async def test_handle_snooze_setting_invalid_value():
    """Callback отклоняет значение не из списка допустимых."""
    cb = _make_callback("settings:snooze:99")
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_snooze_setting(cb)

    cb.message.edit_text.assert_not_called()
    cb.answer.assert_called_once()
    assert cb.answer.call_args.kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_handle_snooze_setting_keyboard_updated():
    """После обновления первая строка клавиатуры отражает новое выбранное значение повтора."""
    cb = _make_callback("settings:snooze:5")
    session = _make_session(settings_obj=_make_user_settings(snooze_minutes=15))

    with patch("app.bot.handlers.settings.AsyncSessionLocal", return_value=session):
        await handle_snooze_setting(cb)

    keyboard = cb.message.edit_text.call_args.kwargs["reply_markup"]
    # Первая строка — кнопки повтора
    snooze_texts = [btn.text for btn in keyboard.inline_keyboard[0]]
    active = [t for t in snooze_texts if "✅" in t]
    assert len(active) == 1
    assert "5" in active[0]


# ---------------------------------------------------------------------------
# send_reminder — интервал повтора из настроек пользователя
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_reminder_uses_user_snooze_minutes():
    """send_reminder использует snooze_minutes из UserSettings пользователя."""
    from apscheduler.triggers.date import DateTrigger

    reminder = _make_reminder_obj(id=1, user_id=100)
    user_settings = _make_user_settings(snooze_minutes=5)
    session = _make_reminder_session(reminder, settings_obj=user_settings)

    mock_msg = MagicMock()
    mock_msg.message_id = 1
    captured_trigger = {}

    def capture_add_job(func, trigger, **kwargs):
        captured_trigger["trigger"] = trigger

    mock_scheduler = MagicMock()
    mock_scheduler.add_job.side_effect = capture_add_job

    fixed_now = datetime.now()
    with patch("app.services.scheduler.AsyncSessionLocal", return_value=session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler", mock_scheduler), \
         patch("app.services.scheduler._now_tz", side_effect=lambda tz: fixed_now):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(1)

    trigger = captured_trigger["trigger"]
    run_date = trigger.run_date.replace(tzinfo=None)
    assert run_date == fixed_now + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_send_reminder_uses_30_min_from_settings():
    """send_reminder использует 30 мин если пользователь выбрал 30."""
    from apscheduler.triggers.date import DateTrigger

    reminder = _make_reminder_obj(id=2, user_id=200)
    user_settings = _make_user_settings(snooze_minutes=30)
    session = _make_reminder_session(reminder, settings_obj=user_settings)

    mock_msg = MagicMock()
    mock_msg.message_id = 1
    captured_trigger = {}

    def capture_add_job(func, trigger, **kwargs):
        captured_trigger["trigger"] = trigger

    mock_scheduler = MagicMock()
    mock_scheduler.add_job.side_effect = capture_add_job

    fixed_now = datetime.now()
    with patch("app.services.scheduler.AsyncSessionLocal", return_value=session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler", mock_scheduler), \
         patch("app.services.scheduler._now_tz", side_effect=lambda tz: fixed_now):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(2)

    trigger = captured_trigger["trigger"]
    run_date = trigger.run_date.replace(tzinfo=None)
    assert run_date == fixed_now + timedelta(minutes=30)


@pytest.mark.asyncio
async def test_send_reminder_fallback_when_no_settings():
    """send_reminder использует REMINDER_REPEAT_MINUTES если нет UserSettings."""
    from apscheduler.triggers.date import DateTrigger

    reminder = _make_reminder_obj(id=3, user_id=300)
    session = _make_reminder_session(reminder, settings_obj=None)

    mock_msg = MagicMock()
    mock_msg.message_id = 1
    captured_trigger = {}

    def capture_add_job(func, trigger, **kwargs):
        captured_trigger["trigger"] = trigger

    mock_scheduler = MagicMock()
    mock_scheduler.add_job.side_effect = capture_add_job

    fixed_now = datetime.now()
    fallback_minutes = 15
    with patch("app.services.scheduler.AsyncSessionLocal", return_value=session), \
         patch("app.services.scheduler.bot") as mock_bot, \
         patch("app.services.scheduler.scheduler", mock_scheduler), \
         patch("app.services.scheduler.REMINDER_REPEAT_MINUTES", fallback_minutes), \
         patch("app.services.scheduler._now_tz", side_effect=lambda tz: fixed_now):
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        await send_reminder(3)

    trigger = captured_trigger["trigger"]
    run_date = trigger.run_date.replace(tzinfo=None)
    assert run_date == fixed_now + timedelta(minutes=fallback_minutes)