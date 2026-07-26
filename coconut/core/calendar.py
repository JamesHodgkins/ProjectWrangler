"""Single global project calendar used for all scheduling date math.

Per-resource calendars are out of scope (see PROJECT_PLAN.md). Defaults to
a Mon-Fri working week; the scheduler must go through this abstraction
rather than raw date arithmetic so richer calendars (custom weekdays,
holidays) can be adjusted later without touching scheduler.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class Calendar:
    non_working_dates: set[date] = field(default_factory=set)
    working_weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})

    def is_working_day(self, day: date) -> bool:
        if day.weekday() not in self.working_weekdays:
            return False
        return day not in self.non_working_dates

    def add_days(self, start: date, num_days: float) -> date:
        """Advance start by num_days working days.

        num_days may be fractional (partial-day durations); the whole-day
        part is stepped one working day at a time and the remainder is
        added directly, since sub-day calendar effects aren't modeled yet.
        """
        whole_days = int(num_days)
        remainder = num_days - whole_days

        current = start
        remaining = whole_days
        step = 1 if remaining >= 0 else -1
        remaining = abs(remaining)
        while remaining > 0:
            current += timedelta(days=step)
            if self.is_working_day(current):
                remaining -= 1

        if remainder:
            current += timedelta(days=remainder * step)
        return current

    def finish_date(self, start: date, duration_days: float) -> date:
        """Returns the finish date of a duration_days-day task starting on
        start, where the start day itself counts toward the duration (a
        1-day task starting on a working day finishes that same day).

        This is deliberately distinct from add_days(), which returns the
        date N working days *after* a given date (used for dependency
        lag/lead, where the anchor date is already "spent" and shouldn't
        count toward the gap). Duration math and lag math need different
        day-zero conventions; conflating them was the cause of a 1-day
        task starting Friday incorrectly finishing Monday instead of
        Friday.
        """
        if not self.is_working_day(start):
            start = self.add_days(start, 1)
        if duration_days <= 0:
            return start
        return self.add_days(start, duration_days - 1)

    def start_date(self, finish: date, duration_days: float) -> date:
        """Inverse of finish_date(): the start date of a duration_days-day
        task that finishes on finish, where the finish day itself counts
        toward the duration.
        """
        if not self.is_working_day(finish):
            finish = self.add_days(finish, -1)
        if duration_days <= 0:
            return finish
        return self.add_days(finish, -(duration_days - 1))

    def working_days_between(self, start: date, end: date) -> int:
        if end < start:
            return -self.working_days_between(end, start)
        count = 0
        current = start
        while current < end:
            current += timedelta(days=1)
            if self.is_working_day(current):
                count += 1
        return count
