"""Hijri-derived date constants for the FHH MENA demand simulation.

These are the SAUDI sighting dates used as the canonical reference. Other
markets (Egypt, Morocco, Jordan) sometimes start fasting one day later,
but for the demo we use a single MENA-wide calendar — that matches how
the dashboard groups events.

Sources cross-referenced:
  - 2023, 2024: KSA's Supreme Court official announcements (post-hoc).
  - 2025-2028:  Umm al-Qura calculated dates (KSA's official calendar).

If a real moon-sighting reschedules a day, downstream consumers should
treat these as best-effort projections, not legal calendars.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


# --- Ramadan: (1 Ramadan, last day of Ramadan) inclusive --------------------
# 2025 Ramadan SPANS Feb→March (1 Ramadan = March 1, last = March 30).
# All other years sit cleanly inside one Gregorian month.
RAMADAN_RANGES: dict[int, tuple[date, date]] = {
    2023: (date(2023, 3, 23), date(2023, 4, 20)),  # 29 days
    2024: (date(2024, 3, 11), date(2024, 4, 9)),   # 30 days
    2025: (date(2025, 3, 1),  date(2025, 3, 30)),  # 30 days  (spans Feb→Mar boundary in pre-stockup window)
    2026: (date(2026, 2, 18), date(2026, 3, 19)),  # 30 days
    2027: (date(2027, 2, 8),  date(2027, 3, 9)),   # 30 days
    2028: (date(2028, 1, 28), date(2028, 2, 25)),  # 29 days
}

# --- Eid al-Fitr: 1-3 Shawwal. We mark the FIRST day (1 Shawwal) here -------
EID_ALFITR: dict[int, date] = {
    2023: date(2023, 4, 21),
    2024: date(2024, 4, 10),
    2025: date(2025, 3, 31),
    2026: date(2026, 3, 20),
    2027: date(2027, 3, 10),
    2028: date(2028, 2, 26),
}

# --- Eid al-Adha: 10 Dhu al-Hijjah ------------------------------------------
EID_ALADHA: dict[int, date] = {
    2023: date(2023, 6, 28),
    2024: date(2024, 6, 16),
    2025: date(2025, 6, 6),
    2026: date(2026, 5, 27),
    2027: date(2027, 5, 16),
    2028: date(2028, 5, 5),
}

PRE_RAMADAN_STOCKUP_DAYS = 7  # the 7 days before 1 Ramadan


def ramadan_days(year: int) -> Iterable[tuple[date, int]]:
    """Yield (date, ramadan_day_1_indexed) for every day of Ramadan in `year`."""
    if year not in RAMADAN_RANGES:
        return
    start, end = RAMADAN_RANGES[year]
    cur = start
    day_idx = 1
    while cur <= end:
        yield cur, day_idx
        cur += timedelta(days=1)
        day_idx += 1


def pre_ramadan_stockup_dates(year: int) -> list[date]:
    if year not in RAMADAN_RANGES:
        return []
    start = RAMADAN_RANGES[year][0]
    return [start - timedelta(days=n) for n in range(PRE_RAMADAN_STOCKUP_DAYS, 0, -1)]


def is_pre_ramadan_stockup(d: date) -> bool:
    return d in pre_ramadan_stockup_dates(d.year) or d in pre_ramadan_stockup_dates(d.year + 1)
