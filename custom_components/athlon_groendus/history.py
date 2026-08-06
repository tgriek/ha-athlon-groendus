"""Turn charging sessions into hourly totals.

Pure stdlib on purpose: no Home Assistant imports, so the maths can be tested
on its own.

A session reports only a total (kWh, cost) with a start and an end -- there is
no per-hour curve. Sessions here run for a median of ~10 hours (car left
plugged in overnight), so the total is spread across every hour the session
covers, weighted by how much of that hour the session occupied. Daily and
monthly totals come out exact; the hour-by-hour shape is an approximation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

HOUR = timedelta(hours=1)

# Sessions the portal did not accept carry no energy we should bill.
REJECTED_STATUS = "REJECTED"


def parse_iso(value: Any) -> datetime | None:
    """Parse a portal timestamp ('2026-07-21T19:03:02.000Z') as an aware datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def floor_hour(moment: datetime) -> datetime:
    """Round down to the top of the hour, which is what the recorder requires."""
    return moment.replace(minute=0, second=0, microsecond=0)


def spread_over_hours(start: datetime, end: datetime, value: float) -> dict[datetime, float]:
    """Split a value across the hours between start and end, by time in each hour."""
    if value == 0.0:
        return {}

    # Zero-length or reversed session: attribute everything to the start hour.
    total_seconds = (end - start).total_seconds()
    if total_seconds <= 0:
        return {floor_hour(start): value}

    buckets: dict[datetime, float] = {}
    cursor = floor_hour(start)
    while cursor < end:
        slot_end = cursor + HOUR
        overlap = (min(end, slot_end) - max(start, cursor)).total_seconds()
        if overlap > 0:
            buckets[cursor] = buckets.get(cursor, 0.0) + value * (overlap / total_seconds)
        cursor = slot_end
    return buckets


def build_hourly_totals(
    transactions: Iterable[dict[str, Any]], chargepoint_id: str | None = None
) -> tuple[dict[datetime, float], dict[datetime, float]]:
    """Return (energy_by_hour, cost_by_hour) for completed, accepted sessions."""
    energy: dict[datetime, float] = {}
    cost: dict[datetime, float] = {}

    for tx in transactions:
        if chargepoint_id and tx.get("chargepointId") != chargepoint_id:
            continue
        if str(tx.get("status") or "").upper() == REJECTED_STATUS:
            continue

        start = parse_iso(tx.get("startDateTime"))
        if start is None:
            continue
        # An unfinished session has no final total yet; skip until it closes.
        end = parse_iso(tx.get("endDateTime"))
        if end is None:
            continue

        for hour, amount in spread_over_hours(start, end, _as_float(tx.get("totalEnergy"))).items():
            energy[hour] = energy.get(hour, 0.0) + amount
        for hour, amount in spread_over_hours(start, end, _as_float(tx.get("totalCost"))).items():
            cost[hour] = cost.get(hour, 0.0) + amount

    return energy, cost


def to_cumulative(buckets: dict[datetime, float]) -> list[tuple[datetime, float, float]]:
    """Return [(hour, value_in_hour, running_total)] ordered oldest first.

    Hours with no charging are left out; the recorder carries the previous sum
    forward, so gaps read as "nothing happened" rather than a reset.
    """
    running = 0.0
    rows: list[tuple[datetime, float, float]] = []
    for hour in sorted(buckets):
        value = buckets[hour]
        running += value
        rows.append((hour, value, running))
    return rows
