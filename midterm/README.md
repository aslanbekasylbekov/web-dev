# SubTrack API

A tracker for your paid subscriptions: Netflix, Spotify, iCloud, the gym...
SubTrack stores them, calculates **when the next charge is coming** and **how much you really spend per month and per year**.

**Stack:** Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL 16, Docker, Docker Compose.

## Quick start

```bash
cp .env.example .env      # create your env file (already included in the submitted zip)
docker compose up --build
```

`docker compose up` alone also works: on the first run Compose builds the backend image automatically.

| What | URL |
|---|---|
| Swagger UI (interactive docs) | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| OpenAPI JSON | http://localhost:8000/openapi.json |
| Health check | http://localhost:8000/health |

## Architecture

```
 host :8000 ──► backend (FastAPI, uvicorn) ──── subtrack_net ────► db (PostgreSQL 16)
                image built from                                    named volume:
                backend/Dockerfile                                  subtrack_db_data
                                                                    (no port published)
```

* **backend**: custom image `subtrack-backend:1.0` built from `backend/Dockerfile` (slim base image, cached dependency layer, non-root user `appuser`, `HEALTHCHECK` on `/health`). Port `8000` of the container is published on the host port `APP_PORT`.
* **db**: official `postgres:16-alpine`. Its port is **not** published to the host; only containers in `subtrack_net` can reach it.
* **Network**: both services are in the user-defined bridge network `subtrack_net`. Docker's built-in DNS resolves the service name, so the backend connects to `db:5432` (`POSTGRES_HOST=db`), not `localhost`.
* **Startup order**: the `db` service has a `pg_isready` healthcheck, and the backend uses `depends_on: condition: service_healthy`, so it starts only when PostgreSQL accepts connections. On startup the backend creates the table if it does not exist.
* **Persistence**: the named volume `subtrack_db_data` is mounted at `/var/lib/postgresql/data`. Data survives `docker compose down` and is deleted only with `docker compose down -v`.

## Environment variables

Defined in `.env` (template: `.env.example`). Compose reads `.env` automatically and passes the values to the containers.

| Variable | Used by | Example | Description |
|---|---|---|---|
| `POSTGRES_DB` | db, backend | `subtrack` | Database name |
| `POSTGRES_USER` | db, backend | `subtrack_user` | Database user |
| `POSTGRES_PASSWORD` | db, backend | `subtrack_password` | Database password |
| `APP_NAME` | backend | `SubTrack API` | Title shown in Swagger |
| `APP_PORT` | compose | `8000` | Host port for the API |

`POSTGRES_HOST=db` and `POSTGRES_PORT=5432` are set directly in `docker-compose.yml` because they describe the Docker network, not secrets.

## Project structure

```
subtrack/
├── backend/
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── requirements.txt
│   └── app/
│       ├── main.py                   # FastAPI app, startup (create tables), /health
│       ├── config.py                 # settings from environment variables
│       ├── database.py               # SQLAlchemy engine and session
│       ├── models.py                 # Subscription table
│       ├── schemas.py                # Pydantic models: request/response, validation rules
│       ├── billing.py                # next payment date, monthly/yearly cost
│       └── routers/subscriptions.py  # CRUD, stats and upcoming endpoints
├── docker-compose.yml
├── .env.example
├── .gitignore
├── postman_collection.json
└── README.md
```

## Useful commands

```bash
docker compose up --build           # build the backend image and start everything
docker compose up -d                # start in the background
docker compose ps                   # status of the containers (and health)
docker compose logs -f backend      # backend logs
docker compose down                 # stop and remove containers, KEEP data
docker compose down -v              # stop and DELETE the database volume
docker compose down --rmi all       # stop and delete the images too (backend and postgres)
docker compose exec db psql -U subtrack_user -d subtrack -c "SELECT * FROM subscriptions;"
docker volume ls                    # the volume is listed as <project>_subtrack_db_data
docker network ls                   # the network is listed as <project>_subtrack_net
```

## Data model: `subscriptions`

| Field | Type | Rules |
|---|---|---|
| `id` | integer | Primary key, assigned automatically |
| `name` | string | Required, 1-100 characters, **unique case-insensitive** (`Netflix` = `netflix`) |
| `category` | enum | `streaming`, `music`, `cloud`, `software`, `gaming`, `education`, `news`, `fitness`, `other` |
| `price` | decimal | Required, > 0, max 2 decimal places. Price for **one** billing period |
| `currency` | enum | `KZT`, `USD`, `EUR`, `RUB` |
| `billing_cycle` | enum | `weekly`, `monthly`, `quarterly`, `yearly` |
| `start_date` | date | Required, date of the first payment (`YYYY-MM-DD`) |
| `active` | boolean | Default `true`. `false` means cancelled |
| `cancelled_at` | date | Only allowed when `active` is `false`. Defaults to today. Must not be earlier than `start_date`. Cleared when the subscription becomes active again |
| `notes` | string | Optional, max 1000 characters |
| `monthly_cost` | decimal | **Computed, read-only**: average cost per month (`price × payments per year / 12`) |
| `next_payment_date` | date | **Computed, read-only**: next charge date (today or later), `null` if cancelled |
| `created_at` | datetime | Set by the database |
| `updated_at` | datetime | Updated on every change |

Unknown fields in a request body (including the computed ones) are rejected with `422`.

Billing math: a monthly subscription started on Jan 31 charges on the last day of shorter months (Feb 28, Apr 30, ...). A weekly price of 10 is 43.33 per month (10 × 52 / 12). Dates are calculated in the server's timezone (UTC inside the container).

## API reference

Base URL: `http://localhost:8000`

| Method | Path | Description | Success | Errors |
|---|---|---|---|---|
| `GET` | `/subscriptions` | List (filters, search, sorting, pagination) | `200` | `422` |
| `GET` | `/subscriptions/{id}` | Get one subscription | `200` | `404`, `422` |
| `POST` | `/subscriptions` | Create | `201` | `409`, `422` |
| `PUT` | `/subscriptions/{id}` | Replace (full update) | `200` | `404`, `409`, `422` |
| `PATCH` | `/subscriptions/{id}` | Partial update | `200` | `404`, `409`, `422` |
| `DELETE` | `/subscriptions/{id}` | Delete | `204` (no body) | `404`, `422` |
| `GET` | `/subscriptions/stats` | Spending statistics | `200` | none |
| `GET` | `/subscriptions/upcoming` | Payments in the next N days | `200` | `422` |
| `GET` | `/health` | Service and database health | `200` | `503` |

### `GET /subscriptions`

| Query parameter | Type | Default | Description |
|---|---|---|---|
| `category` | enum | none | Exact match |
| `currency` | enum | none | Exact match |
| `billing_cycle` | enum | none | Exact match |
| `active` | boolean | none | `true` = active, `false` = cancelled |
| `min_price` | decimal | none | `price >=` value |
| `max_price` | decimal | none | `price <=` value. `min_price > max_price` gives `422` |
| `q` | string | none | Case-insensitive search in `name` and `notes` |
| `sort` | string | `name` | Field name, prefix `-` for descending. Allowed: `id`, `name`, `price`, `start_date`, `created_at`, `category`, `currency`, `billing_cycle` |
| `limit` | integer | `20` | 1-100 |
| `offset` | integer | `0` | Items to skip |

Example: `GET /subscriptions?category=streaming&active=true&sort=-price&limit=10`

Response `200`:

```json
{
  "items": [
    {
      "id": 1,
      "name": "Netflix",
      "category": "streaming",
      "price": 4990.0,
      "currency": "KZT",
      "billing_cycle": "monthly",
      "start_date": "2026-01-15",
      "active": true,
      "cancelled_at": null,
      "notes": "Family plan, shared with my brother",
      "monthly_cost": 4990.0,
      "next_payment_date": "2026-11-15",
      "created_at": "2026-10-31T09:00:00Z",
      "updated_at": "2026-10-31T09:00:00Z"
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

`total` is the number of matching subscriptions before `limit`/`offset` are applied.

### `GET /subscriptions/{id}`

Response `200`: one subscription object (same shape as an item above).
Response `404`: `{"detail": "Subscription 999 not found"}`

### `POST /subscriptions`

Request body (`active`, `cancelled_at`, `notes` are optional):

```json
{
  "name": "Netflix",
  "category": "streaming",
  "price": 4990,
  "currency": "KZT",
  "billing_cycle": "monthly",
  "start_date": "2026-01-15",
  "active": true,
  "notes": "Family plan, shared with my brother"
}
```

Response `201`: the created subscription with `id`, `monthly_cost`, `next_payment_date`, `created_at`, `updated_at`.
Response `409`: `{"detail": "Subscription 'NETFLIX' already exists"}`
Response `422`: validation error, e.g. negative `price`, or `cancelled_at` sent while `active` is `true`.

### `PUT /subscriptions/{id}`

Full update: same body as `POST`. Optional fields that are omitted get their defaults (`active: true`, `notes: null`).
Response `200`: the updated subscription. `404`, `409`, `422` as above.

### `PATCH /subscriptions/{id}`

Partial update: send only the fields to change, the rest keeps its current value. The result is validated with the same rules as `POST`.

```json
{ "active": false }
```

This cancels the subscription: `cancelled_at` becomes today and `next_payment_date` becomes `null`. Sending `{"active": true}` resumes it and clears `cancelled_at`.
Response `200`: the updated subscription. `404`, `409`, `422` as above.

### `DELETE /subscriptions/{id}`

Response `204` with an empty body. `404` if the ID does not exist.

### `GET /subscriptions/stats`

Counters include all subscriptions; money and groupings include **active** subscriptions only. Money is grouped by currency (no conversion).

```json
{
  "total": 3,
  "active": 2,
  "cancelled": 1,
  "monthly_spend": { "KZT": 4990.0, "USD": 2.5 },
  "yearly_spend": { "KZT": 59880.0, "USD": 29.99 },
  "by_category": {
    "streaming": { "count": 1, "monthly_spend": { "KZT": 4990.0 } },
    "cloud": { "count": 1, "monthly_spend": { "USD": 2.5 } }
  },
  "by_billing_cycle": { "monthly": 1, "yearly": 1 },
  "next_payment": { "id": 1, "name": "Netflix", "date": "2026-11-15", "price": 4990.0, "currency": "KZT" }
}
```

`next_payment` is `null` when there are no active subscriptions.

### `GET /subscriptions/upcoming?days=7`

Active subscriptions that charge between today and today + `days` (`days`: 0-365, default 7), sorted by date.

```json
{
  "days": 7,
  "date_from": "2026-10-31",
  "date_to": "2026-11-07",
  "items": [
    {
      "id": 2,
      "name": "Gym",
      "price": 10.0,
      "currency": "USD",
      "billing_cycle": "weekly",
      "next_payment_date": "2026-11-05",
      "days_left": 5
    }
  ],
  "total_due": { "USD": 10.0 }
}
```

### `GET /health`

Response `200`: `{"status": "ok", "database": "up"}`
Response `503`: `{"detail": "Database is unreachable"}`

### Error format

* `404`, `409`, `503` and query errors (bad `sort`, `min_price > max_price`): `{"detail": "message"}`
* `422` from body/parameter validation: `{"detail": [{"type": "...", "loc": ["body", "price"], "msg": "...", "input": ...}]}`

## curl examples

```bash
# create
curl -X POST http://localhost:8000/subscriptions -H "Content-Type: application/json" -d '{
  "name": "Spotify", "category": "music", "price": 1990, "currency": "KZT",
  "billing_cycle": "monthly", "start_date": "2026-01-31"
}'

# list with filters and search
curl "http://localhost:8000/subscriptions?currency=KZT&active=true&sort=-price"
curl "http://localhost:8000/subscriptions?q=spot"

# get / replace / partial update / delete
curl http://localhost:8000/subscriptions/1
curl -X PUT http://localhost:8000/subscriptions/1 -H "Content-Type: application/json" -d '{
  "name": "Spotify", "category": "music", "price": 2490, "currency": "KZT",
  "billing_cycle": "monthly", "start_date": "2026-01-31"
}'
curl -X PATCH http://localhost:8000/subscriptions/1 -H "Content-Type: application/json" -d '{"active": false}'
curl -X DELETE http://localhost:8000/subscriptions/1

# statistics and upcoming payments
curl http://localhost:8000/subscriptions/stats
curl "http://localhost:8000/subscriptions/upcoming?days=30"
```

## Postman

1. Start the stack: `docker compose up`.
2. In Postman: **Import** → select `postman_collection.json`.
3. Run the whole collection with **Run collection** (Collection Runner), or send the requests one by one in order.

The collection variable `baseUrl` is `http://localhost:8000`. Request 2 saves the new ID into `{{subId}}` and request 3 into `{{sub2Id}}`, so Get, PUT, PATCH and Delete work as a chain. Requests 14 and 16 delete both subscriptions again, so the collection can be run repeatedly.

Every request has test assertions (status code and response body). Besides the happy path, the collection checks the error cases: duplicate name (`409`), invalid body (`422`), unknown ID (`404`) and reading a deleted subscription (`404`).

| # | Request | Expected |
|---|---|---|
| 1 | `GET /health` | `200` |
| 2 | `POST /subscriptions` (Netflix) | `201` |
| 3 | `POST /subscriptions` (iCloud, yearly USD) | `201` |
| 4 | `POST /subscriptions` duplicate name | `409` |
| 5 | `POST /subscriptions` invalid body | `422` |
| 6 | `GET /subscriptions` | `200` |
| 7 | `GET /subscriptions` with filters + sort | `200` |
| 8 | `GET /subscriptions/{{subId}}` | `200` |
| 9 | `GET /subscriptions/999999` | `404` |
| 10 | `PUT /subscriptions/{{subId}}` | `200` |
| 11 | `GET /subscriptions/stats` | `200` |
| 12 | `GET /subscriptions/upcoming?days=31` | `200` |
| 13 | `PATCH /subscriptions/{{subId}}` cancel | `200` |
| 14 | `DELETE /subscriptions/{{subId}}` | `204` |
| 15 | `GET /subscriptions/{{subId}}` after delete | `404` |
| 16 | `DELETE /subscriptions/{{sub2Id}}` (cleanup) | `204` |
