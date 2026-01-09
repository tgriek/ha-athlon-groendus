# Athlon Groendus (Home Assistant / HACS)

Home Assistant custom integration (HACS-ready) to fetch **charging sessions** from the Athlon Groendus portal and expose an **Energy Dashboard compatible** kWh total sensor.

## Features

- **Config flow**: enter login details, then **select a chargepoint**
- **Energy Dashboard sensor**: monotonic **total kWh** (`state_class: total_increasing`, `device_class: energy`)
- **Session sensors**: “last session energy” and “last session cost” with useful attributes

## Install (HACS)

1. In Home Assistant: **HACS → Integrations → Custom repositories**
2. Add this repository URL and choose **Integration**
3. Install **Athlon Groendus**
4. Restart Home Assistant
5. Add the integration: **Settings → Devices & services → Add integration → Athlon Groendus**

## Setup

During setup you will be asked for:

- **Email** / **Password** (same credentials as `athlon.groendus.nl`)
- **Chargepoint** (selected from your account)

### Credential storage note

Home Assistant stores integration data in the config entry. This integration stores the credentials so it can poll the cloud API.

## Energy Dashboard

Add the entity **“Athlon charging energy total”** as an energy source in **Settings → Dashboards → Energy**.

## How it works (reverse engineered)

The portal uses:

- **AWS Cognito** for authentication (region `eu-central-1`)
- **AWS AppSync (GraphQL)** for data, including `listTransactions` (charging sessions)

## Standalone verification (no Home Assistant)

If you want to verify login + API calls outside HA, use:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tools/requirements.txt
python tools/verify_standalone.py
```

It reads `ATHLON_GROENDUS_EMAIL` / `ATHLON_GROENDUS_PASSWORD` from your environment or `.env`.


# ha-athlon-groendus
