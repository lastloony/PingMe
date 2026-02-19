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
    _find_dot_ambiguity,
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

    def test_dash_time(self):
        assert _normalize_time("в 10-00") == "в 10:00"

    def test_dash_time_no_leading_zero(self):
        assert _normalize_time("в 9-30") == "в 9:30"

    def test_in_hour_only(self):
        assert _normalize_time("в 20") == "в 20:00"

    def test_in_hour_single_digit(self):
        assert _normalize_time("в 9") == "в 09:00"

    def test_no_change(self):
        assert _normalize_time("встреча завтра") == "встреча завтра"

    def test_dot_time_zero_minutes(self):
        assert _normalize_time("в 18.00") == "в 18:00"

    def test_dot_time_minutes_gt12(self):
        assert _normalize_time("в 18.30") == "в 18:30"

    def test_dot_time_minutes_gt12_small_hour(self):
        assert _normalize_time("в 8.45") == "в 8:45"

    def test_dot_time_ambiguous_not_changed(self):
        # 18.02 — неоднозначно, нормализация не трогает
        assert _normalize_time("встреча 18.02") == "встреча 18.02"


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

    def test_dash_format(self):
        assert _has_explicit_time("завтра в 10-00")

    def test_no_time(self):
        assert not _has_explicit_time("встреча завтра")

    def test_no_time_date_only(self):
        assert not _has_explicit_time("19.02 написать заявление")

    def test_dot_time_zero(self):
        assert _has_explicit_time("встреча завтра в 18.00")

    def test_dot_time_minutes_gt12(self):
        assert _has_explicit_time("встреча завтра в 18.30")

    def test_dot_time_ambiguous_not_explicit(self):
        # 18.02 — неоднозначно, не считается явным временем
        assert not _has_explicit_time("встреча 18.02")


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

    def test_through_hours(self):
        from app.bot.handlers.reminders import _now as _now_msk
        now = _now_msk()
        result = _parse_reminder("выключить таймер через 2 часа", now=now)
        assert result is not None
        text, dt = result
        assert "выключить таймер" in text
        # через 2 часа — должно быть ~2 часа от сейчас, не 02:00 следующего дня
        delta_hours = (dt - now).total_seconds() / 3600
        assert 1.5 < delta_hours < 2.5, f"Ожидалось ~2 ч от сейчас, получили {dt}"

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

    def test_trailing_v_uppercase_removed(self):
        result = _parse_reminder("Наполнить кормушку у дымы В 11:30")
        assert result is not None
        text, _ = result
        assert not text.endswith(" В")
        assert not text.endswith(" в")

    def test_dash_time_format(self):
        result = _parse_reminder("позвонить завтра в 10-00")
        assert result is not None
        text, dt = result
        assert "позвонить" in text
        assert dt.hour == 10
        assert dt.minute == 0

    def test_dash_time_minutes(self):
        result = _parse_reminder("встреча завтра в 14-30")
        assert result is not None
        _, dt = result
        assert dt.hour == 14
        assert dt.minute == 30

    def test_hour_only_format(self):
        result = _parse_reminder("заменить батарейку в 20")
        assert result is not None
        text, dt = result
        assert "заменить батарейку" in text
        assert dt.hour == 20
        assert dt.minute == 0

    def test_slash_date_format(self):
        result = _parse_reminder("дедлайн 20/02 в 18:00")
        assert result is not None
        _, dt = result
        assert dt.day == 20
        assert dt.month == 2
        assert dt.hour == 18

    def test_dot_time_zero_minutes(self):
        result = _parse_reminder("встреча завтра в 18.00")
        assert result is not None
        text, dt = result
        assert "встреча" in text
        assert dt.hour == 18
        assert dt.minute == 0

    def test_dot_time_minutes_gt12(self):
        result = _parse_reminder("встреча завтра в 18.30")
        assert result is not None
        _, dt = result
        assert dt.hour == 18
        assert dt.minute == 30

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


# ---------------------------------------------------------------------------
# _find_dot_ambiguity
# ---------------------------------------------------------------------------

class TestFindDotAmbiguity:
    def test_ambiguous_returns_tuple(self):
        result = _find_dot_ambiguity("встреча 18.02")
        assert result is not None
        fragment, h, mn = result
        assert fragment == "18.02"
        assert h == 18
        assert mn == 2

    def test_ambiguous_small_values(self):
        result = _find_dot_ambiguity("звонок 9.05")
        assert result is not None
        assert result[1] == 9
        assert result[2] == 5

    def test_safe_dot_time_not_ambiguous(self):
        # 18.30 — безопасно, минуты > 12
        assert _find_dot_ambiguity("встреча 18.30") is None

    def test_zero_minutes_not_ambiguous(self):
        # 18.00 — минуты 00, не может быть месяцем
        assert _find_dot_ambiguity("встреча 18.00") is None

    def test_hour_gt23_not_ambiguous(self):
        # 30.04 — часов > 23, это дата 30 апреля
        assert _find_dot_ambiguity("встреча 30.04") is None

    def test_not_ambiguous_when_explicit_time_present(self):
        # Рядом есть явное время → 18.02 это дата, не спрашиваем
        assert _find_dot_ambiguity("встреча 18.02 в 10:00") is None

    def test_full_date_not_ambiguous(self):
        # 18.02.2026 — полная дата, не матчится _AMBIG_DOT_RE
        assert _find_dot_ambiguity("дедлайн 18.02.2026") is None


# ---------------------------------------------------------------------------
# Уточнение времени (FSM waiting_for_time)
# ---------------------------------------------------------------------------

class TestWaitingForTime:
    """
    Проверяем логику которая решает нужно ли спрашивать время.
    Если _has_explicit_time == False — бот должен спросить время.
    Ответ пользователя потом парсится как время к уже известной дате.
    """

    def test_date_only_triggers_time_request(self):
        # Только дата — время не указано, бот должен спросить
        assert not _has_explicit_time("встреча завтра")
        assert not _has_explicit_time("подъем 17.02")
        assert not _has_explicit_time("дедлайн в пятницу")

    def test_date_with_time_no_request(self):
        # Дата + время — бот не должен спрашивать
        assert _has_explicit_time("встреча завтра в 10:00")
        assert _has_explicit_time("подъем 17.02 в 5 утра")
        assert _has_explicit_time("дедлайн в пятницу в 18:00")

    def test_time_answer_parseable(self):
        # Ответ пользователя на уточнение времени должен парситься dateparser-ом
        import dateparser
        from app.bot.handlers.reminders import DATEPARSER_SETTINGS, _normalize_time

        date_str = "17.02.2026"
        for time_input in ["10:00", "9 утра", "7 вечера", "14:30", "10-00", "9-30"]:
            time_str = _normalize_time(time_input)
            dt = dateparser.parse(
                f"{date_str} {time_str}",
                languages=["ru"],
                settings=DATEPARSER_SETTINGS,
            )
            assert dt is not None, f"Не распарсилось: '{time_input}'"
            assert dt.year == 2026
            assert dt.month == 2
            assert dt.day == 17

    def test_time_answer_does_not_override_reminder_text(self):
        # Ответ «10:00» сам по себе не должен создавать новое напоминание —
        # он должен попасть в handle_time_input, а не в remind_from_text.
        # Косвенно проверяем: _parse_reminder("10:00") возвращает результат,
        # но _has_explicit_time("10:00") == True, значит StateFilter(None)
        # защищает от создания дубля — в состоянии waiting_for_time
        # remind_from_text не сработает.
        result = _parse_reminder("10:00")
        assert result is not None  # парсится как время
        assert _has_explicit_time("10:00")  # время явное — без StateFilter создало бы дубль