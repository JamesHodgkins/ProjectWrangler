from datetime import date

from coconut.core.calendar import Calendar


def test_default_calendar_treats_weekends_as_non_working():
    cal = Calendar()
    assert cal.is_working_day(date(2026, 7, 24))  # Friday
    assert not cal.is_working_day(date(2026, 7, 25))  # Saturday
    assert not cal.is_working_day(date(2026, 7, 26))  # Sunday


def test_add_days_advances_by_working_days():
    cal = Calendar()
    # Friday 2026-07-24 + 5 working days: skips the 25th/26th weekend,
    # landing on Friday 2026-07-31.
    result = cal.add_days(date(2026, 7, 24), 5)
    assert result == date(2026, 7, 31)


def test_non_working_dates_are_skipped():
    holiday = date(2026, 7, 27)
    cal = Calendar(non_working_dates={holiday})
    result = cal.add_days(date(2026, 7, 26), 2)
    # 26 -> 27 (holiday, skipped) -> 28 (1) -> 29 (2)
    assert result == date(2026, 7, 29)


def test_working_weekdays_restricts_weekends():
    cal = Calendar(working_weekdays=frozenset({0, 1, 2, 3, 4}))
    # Friday 2026-07-24 + 1 working day should land on Monday 2026-07-27
    result = cal.add_days(date(2026, 7, 24), 1)
    assert result == date(2026, 7, 27)


def test_working_days_between_counts_working_days_only():
    cal = Calendar(working_weekdays=frozenset({0, 1, 2, 3, 4}))
    # Friday 2026-07-24 to Monday 2026-07-27: only Monday is a working day
    assert cal.working_days_between(date(2026, 7, 24), date(2026, 7, 27)) == 1


def test_working_days_between_is_antisymmetric():
    cal = Calendar()
    a, b = date(2026, 7, 24), date(2026, 7, 29)
    assert cal.working_days_between(a, b) == -cal.working_days_between(b, a)
