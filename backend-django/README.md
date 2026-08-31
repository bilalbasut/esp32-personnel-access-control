# PDKS Backend — Node.js → Python/Django Migration

This replaces the old Node.js stack (`server.js` + `collector.js` + `db.js`)
with:

| Old (Node.js)          | New (Python)                              |
|-------------------------|--------------------------------------------|
| `express` + `pg`        | Django (`backend/`) — REST API + web panel |
| `mqtt` (collector.js)   | `paho-mqtt` (`collector/collector.py`)     |
| `db.js` schema block    | Django migrations (`backend/core/migrations/0001_initial.py`) |
| Mosquitto broker        | unchanged — `eclipse-mosquitto:2` in Docker |
| PostgreSQL              | unchanged — `postgres:16` in Docker         |

The ESP32 firmware and MQTT topic contracts are **untouched** — same topics
(`pdks/merkez/dev/+/event`, `/status`, `/hb`, `/cmd/res`), same JSON/binary
payload formats, same ACL binary wire format. Only the server-side stack
changed.

## Project layout

```
pdks-django/
├── docker-compose.yml
├── .env.example
├── mosquitto/config/mosquitto.conf
├── backend/                  # Django app: REST API + admin panel backend
│   ├── manage.py
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── pdks_project/         # settings, root urls
│   └── core/                 # models, views, ACL builder, MQTT publish helper
│       ├── models.py         # employees / cards / devices / access_events / firmware
│       ├── views.py          # every /api/... endpoint from server.js
│       ├── acl.py            # binary ACL builder + publisher (port of publishAclUpdate)
│       ├── mqtt_utils.py      # one-shot MQTT publish helper
│       └── migrations/0001_initial.py
└── collector/                 # paho-mqtt ingestion worker (port of collector.js)
    ├── collector.py
    ├── db.py
    ├── requirements.txt
    └── Dockerfile
```

## What maps to what

- **`db.js`** → Django migrations. `backend/core/migrations/0001_initial.py`
  creates the same tables/columns, plus the two Postgres sequences
  (`acl_version_seq`, `cmd_sequence`) the original schema created directly.
  Run once via `python manage.py migrate` — Django's migration state tracks
  what's applied, replacing the old `CREATE TABLE IF NOT EXISTS` / `ALTER
  TABLE ADD COLUMN IF NOT EXISTS` idempotency trick.
- **`collector.js`** → `collector/collector.py`. Same topic subscriptions,
  same `mapResult`/`mapDir`/`mapMode`/`mapTsrc` translation tables, same
  timestamp sanity check, same upsert-not-blind-update pattern for
  heartbeats, same OTA-status persistence logic. Uses `psycopg2` instead of
  `pg`, `paho-mqtt` instead of `mqtt`.
- **`server.js`** → Django `core/views.py` + `core/urls.py`. Every
  `/api/...` route is ported 1:1, including the raw-SQL PDKS report (window
  functions and all — Django's ORM doesn't do `LEAD() OVER (...) FILTER
  (...)` cleanly, so that query stays raw SQL via `django.db.connection`,
  same as the rest of the reporting/list endpoints). The binary ACL
  publisher (`publishAclUpdate`) is ported byte-for-byte in `core/acl.py`
  using `struct.pack_into` in place of Node's `Buffer`.
- **CORS / static firmware serving** → `django-cors-headers` (open, matching
  `app.use(cors())`) and a `django.views.static.serve` route for
  `/firmware/<file>`, replacing `app.use('/firmware', express.static(...))`.

## Prerequisites

- Docker + Docker Compose v2 (`docker compose version`)
- Nothing else — Python, Postgres, and Mosquitto all run inside containers.

## Setup

1. **Copy the env file and edit it:**

   ```bash
   cp .env.example .env
   ```

   At minimum, set `PANEL_BASE_URL` to this machine's LAN IP (e.g.
   `http://192.168.1.50:3000`) — the ESP32 devices need to reach it for OTA
   downloads and cannot resolve `localhost`.

2. **Build and start everything:**

   ```bash
   docker compose up --build -d
   ```

   This starts, in order of readiness:
   - `postgres` (with a healthcheck the other services wait on)
   - `mosquitto`
   - `backend` — runs `python manage.py migrate` (creates all tables +
     sequences) then serves the API on `:3000`
   - `collector` — waits for the backend's migration to create the schema,
     then connects to Mosquitto and starts ingesting

3. **Check logs:**

   ```bash
   docker compose logs -f backend
   docker compose logs -f collector
   docker compose logs -f mosquitto
   ```

   You should see `Collector connected to Mosquitto MQTT Broker` and
   Django's `Watching for file changes...` / `Starting development server
   at http://0.0.0.0:3000/`.

4. **Point your frontend and ESP32 devices** at the same host/ports as
   before — `MQTT_HOST:1883` for MQTT, `PANEL_BASE_URL` for the REST API.
   No frontend or firmware changes are required; the API paths, JSON
   shapes, and MQTT contracts are unchanged.

## Running without Docker (local dev)

```bash
# 1. Postgres + Mosquitto still need to run somewhere reachable —
#    either docker compose up postgres mosquitto, or your own local install.

# 2. Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export DB_HOST=127.0.0.1 MQTT_HOST=127.0.0.1  # etc, or `set -a; source ../.env; set +a`
python manage.py migrate
python manage.py runserver 0.0.0.0:3000

# 3. Collector (separate terminal / venv)
cd collector
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export DB_HOST=127.0.0.1 MQTT_HOST=127.0.0.1
python collector.py
```

## Notes / behavioral parity details worth knowing

- **No ORM ACL/report magic**: the ACL binary builder and the PDKS report
  both stay close to raw SQL/struct packing on purpose, matching the
  original byte-for-byte and query-for-query, rather than introducing ORM
  behavior differences on data hardware/firmware depend on.
- **`cmd_sequence`**: like the original, the in-process Python counter
  (seeded from the current Unix time) is what's actually used for
  `/api/devices/:id/command`; the `cmd_sequence` Postgres sequence exists
  in the schema for parity but isn't queried, matching `server.js`'s actual
  behavior (not just its comments).
- **Django's `runserver`** is fine for a LAN panel like this (matches the
  original's plain `app.listen`). Swap the backend Dockerfile's `CMD` for
  `gunicorn pdks_project.wsgi:application --bind 0.0.0.0:3000 --workers 3`
  if you want a proper production WSGI server later.
- **Auth**: neither the original `server.js` nor this port add
  authentication to the API — same trust model as before (LAN-only,
  presumably behind your own network boundary).
