"""
Тесты парсера напоминаний.

Запуск:
    docker compose exec bot pytest tests/ -v
    # или локально:
    pytest tests/ -v
"""
from datetime import datetime

import pytest

from app.bot.handlers.reminders import (
    _expand_short_dates,
    _extract_datetime_fragments,
    _has_explicit_time,
    _normalize_time,
    _parse_reminder,
)

# ---------------------------------------------------------------------------
# Вспомогательная функция: проверяем только дату без времени
# ---------------------------------------------------------------------------

def parsed_date(text: str) -> tuple[str, str] | None:
    """Возвращает (текст_напоминания, 'ДД.ММ.ГГГГ ЧЧ:ММ') или None."""
    result = _parse_reminder(text)
    if result is None:
        return None
    reminder_text, dt = result
    return reminder_text, dt.strftime("%d.%m.%Y %H:%M")


# ---------------------------------------------------------------------------
# _normalize_time
# ---------------------------------------------------------------------------

class TestNormalizeTime:
    def test_morning(self):
        assert _normalize_time("в 7 утра") == "в 07:00"

    def test_evening(self):
        assert _normalize_time("в 7 вечера") == "в 19:00"

    def test_evening_form2(self):
        assert _normalize_time("в 7 вечером") == "в 19:00"

    def test_night(self):
        assert _normalize_time("в 2 ночи") == "в 02:00"

    def test_day(self):
        assert _normalize_time("в 2 дня") == "в 14:00"

    def test_hours(self):
        assert _normalize_time("в 13 часов") == "в 13:00"

    def test_hours_genitive(self):
        assert _normalize_time("в 9 часа") == "в 09:00"

    def test_no_change(self):
        assert _normalize_time("встреча завтра") == "встреча завтра"


# ---------------------------------------------------------------------------
# _expand_short_dates
# ---------------------------------------------------------------------------

class TestExpandShortDates:
    def test_dd_mm(self):
        year = datetime.now().year
        assert _expand_short_dates("19.02") == f"19.02.{year}"

    def test_already_full(self):
        assert _expand_short_dates("19.02.2026") == "19.02.2026"

    def test_with_time(self):
        year = datetime.now().year
        assert _expand_short_dates("19.02 13:00") == f"19.02.{year} 13:00"


# ---------------------------------------------------------------------------
# _has_explicit_time
# ---------------------------------------------------------------------------

class TestHasExplicitTime:
    def test_hhmm(self):
        assert _has_explicit_time("завтра в 10:00")

    def test_morning(self):
        assert _has_explicit_time("завтра в 7 утра")

    def test_evening(self):
        assert _has_explicit_time("в 7 вечера")

    def test_through(self):
        assert _has_explicit_time("через 30 минут")

    def test_hours(self):
        assert _has_explicit_time("через 2 часа")

    def test_no_time(self):
        assert not _has_explicit_time("встреча завтра")

    def test_no_time_date_only(self):
        assert not _has_explicit_time("19.02 написать заявление")


# ---------------------------------------------------------------------------
# _extract_datetime_fragments
# ---------------------------------------------------------------------------

class TestExtractFragments:
    def test_numeric_date_and_time(self):
        frags = _extract_datetime_fragments("написать 19.02 в 13:00")
        assert "19.02" in frags
        assert "13:00" in frags

    def test_relative_date(self):
        frags = _extract_datetime_fragments("встреча завтра в 10:00")
        assert "завтра" in frags
        assert "10:00" in frags

    def test_weekday(self):
        frags = _extract_datetime_fragments("в пятницу в 15:00")
        assert any("пятниц" in f.lower() for f in frags)

    def test_no_duplicates(self):
        frags = _extract_datetime_fragments("19.02 встреча 19.02 в 13:00")
        assert frags.count("19.02") == 1

    def test_empty(self):
        assert _extract_datetime_fragments("просто текст без даты") == []


# ---------------------------------------------------------------------------
# _parse_reminder — основные сценарии
# ---------------------------------------------------------------------------

class TestParseReminder:

    # --- Должны парситься ---

    def test_date_and_time(self):
        result = _parse_reminder("написать заявление 20.02 в 13:40")
        assert result is not None
        text, dt = result
        assert "написать заявление" in text
        assert dt.day == 20
        assert dt.month == 2
        assert dt.hour == 13
        assert dt.minute == 40

    def test_tomorrow_with_time(self):
        result = _parse_reminder("позвонить маме завтра в 10:00")
        assert result is not None
        text, dt = result
        assert "позвонить маме" in text
        tomorrow = (datetime.now().date().day + 1)
        # просто проверяем что время правильное
        assert dt.hour == 10
        assert dt.minute == 0

    def test_morning_form(self):
        result = _parse_reminder("подъем 17.02 в 5 утра")
        assert result is not None
        text, dt = result
        assert "подъем" in text
        assert dt.day == 17
        assert dt.hour == 5

    def test_evening_form(self):
        result = _parse_reminder("встреча завтра в 7 вечера")
        assert result is not None
        _, dt = result
        assert dt.hour == 19

    def test_hours_form(self):
        result = _parse_reminder("напомни про стрижку завтра в 13 часов")
        assert result is not None
        text, dt = result
        assert "стрижку" in text
        assert dt.hour == 13

    def test_prefix_napomni_stripped(self):
        result = _parse_reminder("напомни позвонить завтра в 10:00")
        assert result is not None
        text, _ = result
        assert "напомни" not in text.lower()

    def test_prefix_napomni_mne_stripped(self):
        result = _parse_reminder("напомни мне купить хлеб завтра в 18:00")
        assert result is not None
        text, _ = result
        assert "напомни" not in text.lower()
        assert "мне" not in text.lower()

    def test_through_minutes(self):
        result = _parse_reminder("выпить таблетку через 30 минут")
        assert result is not None
        text, dt = result
        assert "таблетку" in text
        assert dt > datetime.now()

    def test_weekday(self):
        result = _parse_reminder("встреча в пятницу в 15:00")
        assert result is not None
        _, dt = result
        assert dt.hour == 15
        assert dt > datetime.now()

    def test_full_date(self):
        result = _parse_reminder("дедлайн 20.02.2026 в 18:00")
        assert result is not None
        _, dt = result
        assert dt.day == 20
        assert dt.month == 2
        assert dt.year == 2026

    def test_date_leftover_removed_from_text(self):
        result = _parse_reminder("написать 19.02 в 13:00")
        assert result is not None
        text, _ = result
        assert "19" not in text
        assert "13" not in text

    def test_trailing_v_removed(self):
        result = _parse_reminder("включить посудомойку в 08:55")
        assert result is not None
        text, _ = result
        assert not text.endswith(" в")
        assert "включить посудомойку" in text

    # --- Не должны парситься ---

    def test_no_date_returns_none(self):
        assert _parse_reminder("просто текст без даты") is None

    def test_random_text_returns_none(self):
        assert _parse_reminder("привет как дела") is None

    def test_only_text_no_time(self):
        # Дата есть (завтра), время нет — должно распарситься, но _has_explicit_time = False
        result = _parse_reminder("встреча завтра")
        assert result is not None
        assert not _has_explicit_time("встреча завтра")