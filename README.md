# Athlon Groendus (Home Assistant / HACS)

Home Assistant custom integration (HACS-ready) to fetch **charging sessions** from the Athlon Groendus portal and expose an **Energy Dashboard compatible** kWh total sensor.

## Features

- **Config flow**: enter login details, then **select a chargepoint**
- **Energy Dashboard sensor**: monotonic **total kWh** (`state_class: total_increasing`, `device_class: energy`)
- **Session sensors**: “last session energy” and “last session cost” with useful attributes
- **Historical backfill**: imports the full portal history (energy and cost) as long-term statistics

## Install (HACS)

1. In Home Assistant: **HACS → Integrations → Custom repositories**
2. Add this repository URL and choose **Integration**
3. Install **Athlon Groendus**
4. Restart Home Assistant
5. Add the integration: **Settings → Devices & services → Add integration → Athlon Groendus**

## Setup

During setup you will be asked for:

- **Email** / **Password** (same credentials as the portal)
- **Portal URL** (default `https://thuisladen.groendus.nl/`)
- **Label** (optional — leave empty to derive it from the portal URL)
- **Chargepoint** (selected from your account)

Portal URL and label can be changed later via **Configure** on the integration, without removing and re-adding it. The entry reloads automatically when you save.

### Portal URL and label

The Groendus charging portal is white-label: one Cognito user pool and one AppSync API serve several lease companies, and the tenant (**label**) your account belongs to is sent to Cognito on every login. A Lambda trigger validates it, so a wrong label fails with *"User is not part of the &lt;label&gt; label"* even when your password is correct.

The portal moved from `athlon.groendus.nl` (label `athlon`) to `thuisladen.groendus.nl` (label `groendus`). If it moves again, update the portal URL in **Configure** — the integration reads the Cognito and AppSync endpoints from `<portal-url>api/config` at runtime, so only the URL needs to change.

### Credential storage note

Home Assistant stores integration data in the config entry. This integration stores the credentials so it can poll the cloud API.

## Energy Dashboard

Add the entity **“Athlon charging energy total”** as an energy source in **Settings → Dashboards → Energy**.

## Historical data

The portal keeps your full session history, so the Energy Dashboard can be backfilled with charging that happened before the integration was installed.

The history is imported automatically: once when Home Assistant starts, and again whenever a new session appears. You can also trigger it by hand from **Developer tools → Actions**:

```yaml
action: athlon_groendus.import_history
data: {}
```

It is safe to run repeatedly — statistics are keyed on (statistic id, hour), so a re-run overwrites those hours rather than adding to them.

This creates two **external statistics**:

- `athlon_groendus:<chargepoint>_energy` — kWh
- `athlon_groendus:<chargepoint>_cost` — in the tariff currency

### Using it in the Energy Dashboard

In **Settings → Dashboards → Energy → Individual devices → Add device**, pick the `athlon_groendus:..._energy` statistic.

The Energy Dashboard tracks **energy only** for individual devices — `DeviceConsumption` has no cost field, so the `..._cost` statistic cannot be attached there (per-source cost tracking exists only for grid, gas and water). Use it in a statistics card, a template, or the statistics graph instead.

> **Do not also keep the live `sensor.athlon_charging_energy_total` as a source.** The external statistic already covers every session including new ones, so having both counts the same kWh twice.

### Accuracy

A session reports a total with a start and an end — there is no per-hour meter curve. The total is spread across the hours the session covers, weighted by time in each hour. **Daily, monthly and yearly totals are exact**; the hour-by-hour shape is an approximation. Sessions the portal marked `REJECTED`, and sessions that have not finished yet, are excluded.

## How it works (reverse engineered)

The portal uses:

- A runtime config endpoint at `<portal-url>api/config`, which publishes the Cognito user pool / client id and the AppSync URL (this is what the frontend itself boots with). It needs a `Referer` header or it answers 502.
- **AWS Cognito** for authentication (region `eu-central-1`), with `ClientMetadata` `{client: "Portal", label: <label>, portalUrl: <portal-url>}`
- **AWS AppSync (GraphQL)** for data, including `listTransactions` (charging sessions)

If the config endpoint is unreachable, the integration falls back to the endpoint values bundled in `const.py`.

## Standalone verification (no Home Assistant)

If you want to verify login + API calls outside HA, use:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tools/requirements.txt
python tools/verify_standalone.py

# or against a different portal / label:
python tools/verify_standalone.py https://thuisladen.groendus.nl/ groendus
```

It reads `ATHLON_GROENDUS_EMAIL` / `ATHLON_GROENDUS_PASSWORD` from your environment or `.env`.


# ha-athlon-groendus
