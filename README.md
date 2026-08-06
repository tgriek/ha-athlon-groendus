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
