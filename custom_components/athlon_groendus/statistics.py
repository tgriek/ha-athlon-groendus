"""Backfill Home Assistant long-term statistics from portal history.

The portal keeps the full session history, so the Energy Dashboard can be given
real data from before the integration was installed.

These are *external* statistics (`athlon_groendus:<chargepoint>_energy`) rather
than statistics on the existing sensor. The recorder owns a sensor's statistics
and recompiles them from live state, so rows imported onto the sensor's own id
would be overwritten. External ids are independent and stable.

Because of that, adding the external statistic to the Energy Dashboard means
the live sensor must NOT also be configured as a source, or the same kWh is
counted twice.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .api import AthlonGroendusClient
from .const import DOMAIN
from .history import build_hourly_totals, to_cumulative

_LOGGER = logging.getLogger(__name__)

# Statistics are fetched in one pass; the account history is small (low
# hundreds of sessions) but cap the paging so a surprise never loops forever.
_PAGE_SIZE = 100
_MAX_PAGES = 50


def statistic_ids(chargepoint_id: str) -> tuple[str, str]:
    """Return the (energy, cost) statistic ids for a chargepoint."""
    # A statistic id is <domain>:<slug>, and the slug may not contain '__'.
    slug = slugify(chargepoint_id) or "chargepoint"
    return f"{DOMAIN}:{slug}_energy", f"{DOMAIN}:{slug}_cost"


async def _fetch_all_transactions(client: AthlonGroendusClient) -> list[dict[str, Any]]:
    """Page through the whole transaction history, oldest first."""
    items: list[dict[str, Any]] = []
    for page in range(1, _MAX_PAGES + 1):
        result = await client.list_transactions(
            page=page, size=_PAGE_SIZE, sort={"startDateTime": "ASC"}
        )
        batch = result.get("items") or []
        if not batch:
            break
        items.extend(batch)
        total = int(result.get("totalCount") or 0)
        if total and len(items) >= total:
            break
    return items


async def async_import_history(
    hass: HomeAssistant,
    client: AthlonGroendusClient,
    chargepoint_id: str,
    currency: str | None = None,
) -> dict[str, Any]:
    """Import the full session history as long-term statistics.

    Safe to re-run: statistics are keyed on (statistic_id, hour), so a repeat
    import overwrites those hours instead of appending to them.
    """
    # Imported lazily so the integration still loads on installs where the
    # recorder is unavailable, and so the version shim below stays local.
    from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
    from homeassistant.components.recorder.statistics import async_add_external_statistics

    def _metadata(statistic_id: str, name: str, unit: str | None, unit_class: str | None):
        meta: StatisticMetaData = {
            "has_sum": True,
            "name": name,
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_of_measurement": unit,
            "unit_class": unit_class,
        }
        # mean_type replaced has_mean; has_mean is removed in HA 2026.4 and
        # omitting mean_type breaks in 2026.11. Support both eras.
        try:
            from homeassistant.components.recorder.models import StatisticMeanType

            meta["mean_type"] = StatisticMeanType.NONE
        except ImportError:  # HA older than the mean_type migration
            meta["has_mean"] = False
        return meta

    transactions = await _fetch_all_transactions(client)
    energy_buckets, cost_buckets = build_hourly_totals(transactions, chargepoint_id)

    if not energy_buckets:
        _LOGGER.warning(
            "No completed sessions found for chargepoint %s; nothing to import", chargepoint_id
        )
        return {"sessions": len(transactions), "hours": 0, "energy_kwh": 0.0, "cost": 0.0}

    energy_id, cost_id = statistic_ids(chargepoint_id)

    energy_rows = to_cumulative(energy_buckets)
    energy_stats: list[StatisticData] = [
        {"start": hour, "state": value, "sum": running} for hour, value, running in energy_rows
    ]
    async_add_external_statistics(
        hass,
        _metadata(energy_id, f"Athlon charging energy {chargepoint_id}", "kWh", "energy"),
        energy_stats,
    )

    cost_rows = to_cumulative(cost_buckets)
    if cost_rows:
        cost_stats: list[StatisticData] = [
            {"start": hour, "state": value, "sum": running} for hour, value, running in cost_rows
        ]
        # No unit converter exists for money, so the unit class must be None.
        async_add_external_statistics(
            hass,
            _metadata(cost_id, f"Athlon charging cost {chargepoint_id}", currency or "EUR", None),
            cost_stats,
        )

    summary = {
        "sessions": len(transactions),
        "hours": len(energy_rows),
        "energy_kwh": round(energy_rows[-1][2], 3),
        "cost": round(cost_rows[-1][2], 2) if cost_rows else 0.0,
        "first_hour": energy_rows[0][0].isoformat(),
        "last_hour": energy_rows[-1][0].isoformat(),
        "statistic_ids": [energy_id] + ([cost_id] if cost_rows else []),
    }
    _LOGGER.info(
        "Imported %s hours of history for %s (%s kWh, %s) from %s sessions",
        summary["hours"],
        chargepoint_id,
        summary["energy_kwh"],
        summary["cost"],
        summary["sessions"],
    )
    return summary
