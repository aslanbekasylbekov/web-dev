# SubTrack API (hw3)

A tracker for your paid subscriptions: Netflix, Spotify, iCloud, the gym...
SubTrack stores them **grouped by category**, calculates **when the next charge is coming** and **how much you really spend**, and keeps the **history of real payments**.

This is the midterm SubTrack API extended to a relational model with three related entities.

**Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (ORM), PostgreSQL 16, Docker, Docker Compose.

## What changed since the midterm

| Midterm | hw3 |
|---|---|
| One table: `subscriptions` | Three tables: `categories` → `subscriptions` → `payments` |
| `category` was a fixed enum (`streaming`, `music`...) | `category_id` is a foreign key to the `categories` table; you create your own categories |
| No payment history | `payments` table: every real charge of a subscription |
| 9 endpoints | 22 endpoints, including related data: `/categories/{id}/subscriptions`, `/subscriptions/{id}/payments` |
| | New computed fields: `category_name`, `payments_count`, `total_paid`, `last_paid_at`; `total_paid` in `/stats` |

## Quick start

```bash
cp .env.example .env      # create your env file
docker compose up --build
```

| What | URL |
|---|---|
| Swagger UI (interactive docs) | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| OpenAPI JSON | http://localhost:8000/openapi.json |
| Health check | http://localhost:8000/health |

The midterm also uses port `8000`: stop it first (`docker compose down` in `midterm/`), or set another `APP_PORT` in `.env`. Container, volume and network names are different from the midterm (`subtrack_hw3_*`), so the two databases never mix.

## Architecture

```
 host :8000 ──► backend (FastAPI, uvicorn) ──── subtrack_hw3_net ────► db (PostgreSQL 16)
                image subtrack-backend:2.0                              volume subtrack_hw3_db_data
                built from backend/Dockerfile                           (no port published)
```

Same setup as the midterm: the backend waits for the `pg_isready` healthcheck of `db`, connects to `db:5432` through the Docker network, and creates the tables on startup. Data survives `docker compose down` and is deleted with `docker compose down -v`.

## Data model

```
┌────────────────┐ 1      N ┌───────────────────────────┐ 1      N ┌───────────────────────┐
│   categories   │──────────│       subscriptions       │──────────│       payments        │
├────────────────┤          ├───────────────────────────┤          ├───────────────────────┤
│ id PK          │          │ id PK                     │          │ id PK                 │
│ name UNIQUE    │          │ category_id FK            │          │ subscription_id FK    │
│ description    │          │ name UNIQUE               │          │ paid_at               │
│ created_at     │          │ price, currency           │          │ amount                │
│ updated_at     │          │ billing_cycle, start_date │          │ note                  │
└────────────────┘          │ active, cancelled_at      │          │ UNIQUE(subscription_id│
                            │ notes, created_at ...     │          │        , paid_at)     │
                            └───────────────────────────┘          └───────────────────────┘
          ON DELETE RESTRICT (409)                     ON DELETE CASCADE
```

| Relationship | Type | Delete behaviour |
|---|---|---|
| Category → Subscriptions | one-to-many (`subscriptions.category_id`) | A category that still has subscriptions **cannot** be deleted (`409`). Move them (PATCH `category_id`) or delete them first |
| Subscription → Payments | one-to-many (`payments.subscription_id`) | Deleting a subscription deletes its payments (cascade) |

Both are SQLAlchemy `relationship()`s backed by foreign keys in PostgreSQL. Names are unique through case-insensitive unique indexes (`lower(name)`).

### `categories`

| Field | Type | Rules |
|---|---|---|
| `id` | integer | Primary key, assigned automatically |
| `name` | string | Required, 1-50 characters, **unique case-insensitive** (`Streaming` = `streaming`) |
| `description` | string | Optional, max 500 characters |
| `subscription_count` | integer | **Computed, read-only**: number of subscriptions in the category |
| `created_at`, `updated_at` | datetime | Set by the database |

### `subscriptions`

Same fields and rules as in the midterm, but `category` is replaced by `category_id`.

| Field | Type | Rules |
|---|---|---|
| `id` | integer | Primary key |
| `category_id` | integer | Required, an existing category (`404` otherwise) |
| `category_name` | string | **Read-only**, name of the category |
| `name` | string | Required, 1-100 characters, **unique case-insensitive** |
| `price` | decimal | Required, > 0, max 2 decimal places. Price for **one** billing period |
| `currency` | enum | `KZT`, `USD`, `EUR`, `RUB`. **Cannot change once the subscription has payments** (`409`) |
| `billing_cycle` | enum | `weekly`, `monthly`, `quarterly`, `yearly` |
| `start_date` | date | Required, date of the first charge. Not later than the first recorded payment |
| `active` | boolean | Default `true`. `false` means cancelled |
| `cancelled_at` | date | Only when `active` is `false`. Defaults to today. Not earlier than `start_date` or the last payment |
| `notes` | string | Optional, max 1000 characters |
| `monthly_cost` | decimal | **Computed**: `price × payments per year / 12` |
| `next_payment_date` | date | **Computed**: next charge date (today or later), `null` if cancelled |
| `payments_count` | integer | **Computed**: number of recorded payments |
| `total_paid` | decimal | **Computed**: sum of recorded payments (in the subscription's currency) |
| `last_paid_at` | date | **Computed**: date of the latest payment, `null` if none |
| `created_at`, `updated_at` | datetime | Set by the database |

### `payments`

| Field | Type | Rules |
|---|---|---|
| `id` | integer | Primary key |
| `subscription_id` | integer | Taken from the URL when created, cannot be changed |
| `subscription_name` | string | **Read-only**, name of the subscription |
| `paid_at` | date | Required. Not in the future, not before the subscription's `start_date`, not after its `cancelled_at`. **One payment per subscription per day** (`409`) |
| `amount` | decimal | > 0, max 2 decimal places. **Defaults to the subscription's current price** |
| `currency` | enum | **Read-only**, always the subscription's currency |
| `note` | string | Optional, max 500 characters (e.g. which card) |
| `created_at`, `updated_at` | datetime | Set by the database |

Unknown fields in a request body (including the computed ones) are rejected with `422`.

## API reference

Base URL: `http://localhost:8000`. All bodies are JSON.

| # | Method | Path | Description | Success | Errors |
|---|---|---|---|---|---|
| 1 | `GET` | `/health` | Service and database health | `200` | `503` |
| 2 | `GET` | `/categories` | List categories | `200` | `422` |
| 3 | `POST` | `/categories` | Create a category | `201` | `409`, `422` |
| 4 | `GET` | `/categories/{category_id}` | Get a category | `200` | `404`, `422` |
| 5 | `PUT` | `/categories/{category_id}` | Replace a category | `200` | `404`, `409`, `422` |
| 6 | `PATCH` | `/categories/{category_id}` | Partially update a category | `200` | `404`, `409`, `422` |
| 7 | `DELETE` | `/categories/{category_id}` | Delete an empty category | `204` | `404`, `409`, `422` |
| 8 | `GET` | `/categories/{category_id}/subscriptions` | **Related:** subscriptions of a category | `200` | `404`, `422` |
| 9 | `GET` | `/subscriptions` | List subscriptions | `200` | `422` |
| 10 | `GET` | `/subscriptions/stats` | Spending statistics | `200` | none |
| 11 | `GET` | `/subscriptions/upcoming` | Charges in the next N days | `200` | `422` |
| 12 | `GET` | `/subscriptions/{sub_id}` | Get a subscription | `200` | `404`, `422` |
| 13 | `POST` | `/subscriptions` | Create a subscription | `201` | `404`, `409`, `422` |
| 14 | `PUT` | `/subscriptions/{sub_id}` | Replace a subscription | `200` | `404`, `409`, `422` |
| 15 | `PATCH` | `/subscriptions/{sub_id}` | Partially update (cancel, move to another category...) | `200` | `404`, `409`, `422` |
| 16 | `DELETE` | `/subscriptions/{sub_id}` | Delete a subscription and its payments | `204` | `404`, `422` |
| 17 | `GET` | `/subscriptions/{sub_id}/payments` | **Related:** payment history | `200` | `404`, `422` |
| 18 | `POST` | `/subscriptions/{sub_id}/payments` | **Related:** record a payment | `201` | `404`, `409`, `422` |
| 19 | `GET` | `/payments` | List all payments | `200` | `422` |
| 20 | `GET` | `/payments/{payment_id}` | Get a payment | `200` | `404`, `422` |
| 21 | `PATCH` | `/payments/{payment_id}` | Partially update a payment | `200` | `404`, `409`, `422` |
| 22 | `DELETE` | `/payments/{payment_id}` | Delete a payment | `204` | `404`, `422` |

A non-integer ID in the path (`/subscriptions/abc`) returns `422`.

### Status codes

| Code | When |
|---|---|
| `200 OK` | Successful GET, PUT, PATCH |
| `201 Created` | Successful POST, the body is the created object |
| `204 No Content` | Successful DELETE, empty body |
| `404 Not Found` | The ID in the path, or `category_id` in a body, does not exist |
| `409 Conflict` | Duplicate name; second payment on the same day; deleting a category that has subscriptions; changing the currency of a subscription with payments |
| `422 Unprocessable Entity` | Invalid body or query parameters, broken date rule |
| `503 Service Unavailable` | `/health` cannot reach the database |

### Error format

* `404`, `409`, `503`, business-rule and query `422` errors: `{"detail": "message"}`
* `422` from body or parameter validation: `{"detail": [{"type": "...", "loc": ["body", "price"], "msg": "...", "input": ...}]}`

### Lists: pagination, sorting, search

Every list endpoint returns a page:

```json
{ "items": [ ... ], "total": 2, "limit": 20, "offset": 0 }
```

`total` is the number of matching records before `limit`/`offset` are applied.

| Common parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | integer | `20` | 1-100 |
| `offset` | integer | `0` | Records to skip |
| `sort` | string | see endpoint | Field name, prefix `-` for descending. Unknown field → `422` |

---

### 1. `GET /health`

Response `200`: `{"status": "ok", "database": "up"}`
Response `503`: `{"detail": "Database is unreachable"}`

---

### 2. `GET /categories`

| Query parameter | Type | Description |
|---|---|---|
| `q` | string | Case-insensitive search in `name` and `description` |
| `sort` | string | `id`, `name` (default), `created_at`, `subscription_count` |
| `limit`, `offset` | integer | Pagination |

Example: `GET /categories?q=stream&sort=-subscription_count`

Response `200`:

```json
{
  "items": [
    {
      "id": 1,
      "name": "Streaming",
      "description": "Video and TV services",
      "subscription_count": 1,
      "created_at": "2026-11-17T09:00:00Z",
      "updated_at": "2026-11-17T09:00:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### 3. `POST /categories`

```json
{ "name": "Streaming", "description": "Video and TV services" }
```

Response `201`: the category, `subscription_count` is `0`.
Response `409`: `{"detail": "Category 'streaming' already exists"}`
Response `422`: empty `name`, too long fields, unknown fields.

### 4. `GET /categories/{category_id}`

Response `200`: one category. Response `404`: `{"detail": "Category 999999 not found"}`

### 5. `PUT /categories/{category_id}`

Full update, same body as `POST`. An omitted `description` becomes `null`.
Response `200`: the updated category. `404`, `409`, `422` as above.

### 6. `PATCH /categories/{category_id}`

Only the fields to change, validated with the same rules as `POST`.

```json
{ "description": "Movies and series" }
```

Response `200`: the updated category. `404`, `409`, `422` as above.

### 7. `DELETE /categories/{category_id}`

Response `204`, empty body.
Response `409` if it still has subscriptions: `{"detail": "Category 'Streaming' still has 1 subscription(s); move or delete them first"}`
Response `404` if it does not exist.

### 8. `GET /categories/{category_id}/subscriptions`

Subscriptions of one category. Same query parameters as `GET /subscriptions` (9), except `category_id`.
Response `200`: page of subscriptions. Response `404` if the category does not exist.

---

### 9. `GET /subscriptions`

| Query parameter | Type | Default | Description |
|---|---|---|---|
| `category_id` | integer | none | Only this category |
| `currency` | enum | none | Exact match |
| `billing_cycle` | enum | none | Exact match |
| `active` | boolean | none | `true` = active, `false` = cancelled |
| `min_price` | decimal | none | `price >=` value |
| `max_price` | decimal | none | `price <=` value. `min_price > max_price` gives `422` |
| `q` | string | none | Case-insensitive search in `name` and `notes` |
| `sort` | string | `name` | `id`, `name`, `price`, `start_date`, `created_at`, `currency`, `billing_cycle`, `category_id` |
| `limit`, `offset` | integer | `20`, `0` | Pagination |

Example: `GET /subscriptions?category_id=1&active=true&sort=-price&limit=10`

Response `200`:

```json
{
  "items": [
    {
      "id": 1,
      "category_id": 1,
      "category_name": "Streaming",
      "name": "Netflix",
      "price": 4990.0,
      "currency": "KZT",
      "billing_cycle": "monthly",
      "start_date": "2026-01-15",
      "active": true,
      "cancelled_at": null,
      "notes": "Family plan, shared with my brother",
      "monthly_cost": 4990.0,
      "next_payment_date": "2026-12-15",
      "payments_count": 2,
      "total_paid": 9980.0,
      "last_paid_at": "2026-11-15",
      "created_at": "2026-11-17T09:00:00Z",
      "updated_at": "2026-11-17T09:00:00Z"
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

### 10. `GET /subscriptions/stats`

Counters include all subscriptions; money and groupings include **active** subscriptions only. Money is grouped by currency (no conversion). `total_paid` and `payments_count` cover all recorded payments.

```json
{
  "total": 2,
  "active": 2,
  "cancelled": 0,
  "monthly_spend": { "KZT": 4990.0, "USD": 2.5 },
  "yearly_spend": { "KZT": 59880.0, "USD": 29.99 },
  "by_category": {
    "Streaming": { "count": 1, "monthly_spend": { "KZT": 4990.0 } },
    "Cloud": { "count": 1, "monthly_spend": { "USD": 2.5 } }
  },
  "by_billing_cycle": { "monthly": 1, "yearly": 1 },
  "next_payment": { "id": 2, "name": "iCloud+ 50GB", "date": "2026-12-01", "price": 29.99, "currency": "USD" },
  "total_paid": { "KZT": 9980.0 },
  "payments_count": 2
}
```

`next_payment` is `null` when there are no active subscriptions.

### 11. `GET /subscriptions/upcoming`

| Query parameter | Type | Default | Description |
|---|---|---|---|
| `days` | integer | `7` | Look-ahead, 0-365 |
| `category_id` | integer | none | Only this category |

Active subscriptions that charge between today and today + `days`, sorted by date.

```json
{
  "days": 31,
  "date_from": "2026-11-17",
  "date_to": "2026-12-18",
  "items": [
    {
      "id": 2,
      "name": "iCloud+ 50GB",
      "category_name": "Cloud",
      "price": 29.99,
      "currency": "USD",
      "billing_cycle": "yearly",
      "next_payment_date": "2026-12-01",
      "days_left": 14
    }
  ],
  "total_due": { "USD": 29.99 }
}
```

### 12. `GET /subscriptions/{sub_id}`

Response `200`: one subscription (shape as in 9). Response `404`: `{"detail": "Subscription 999999 not found"}`

### 13. `POST /subscriptions`

Body (`active`, `cancelled_at`, `notes` optional):

```json
{
  "category_id": 1,
  "name": "Netflix",
  "price": 4990,
  "currency": "KZT",
  "billing_cycle": "monthly",
  "start_date": "2026-01-15",
  "active": true,
  "notes": "Family plan, shared with my brother"
}
```

Response `201`: the created subscription with `id`, `category_name` and the computed fields.
Response `404`: `{"detail": "Category 999999 not found"}`
Response `409`: `{"detail": "Subscription 'NETFLIX' already exists"}`
Response `422`: e.g. negative `price`, unknown `currency`, or `cancelled_at` sent while `active` is `true`.

### 14. `PUT /subscriptions/{sub_id}`

Full update: same body as `POST`. Optional fields that are omitted get their defaults (`active: true`, `notes: null`).
Response `200`: the updated subscription. `404`, `409`, `422` as above, plus the payment rules:

* `409`: `{"detail": "Cannot change currency: the subscription has 2 payment(s) in KZT"}`
* `422`: `{"detail": "start_date must not be later than the first payment (2026-09-15)"}`
* `422`: `{"detail": "cancelled_at must not be earlier than the last payment (2026-10-15)"}`

### 15. `PATCH /subscriptions/{sub_id}`

Only the fields to change; the result is validated with the same rules as `PUT`.

```json
{ "active": false }
```

Cancels the subscription: `cancelled_at` becomes today and `next_payment_date` becomes `null`. `{"active": true}` resumes it. `{"category_id": 2}` moves it to another category.
Response `200`: the updated subscription. `404`, `409`, `422` as in 14.

### 16. `DELETE /subscriptions/{sub_id}`

Response `204`, empty body. All payments of the subscription are deleted too. `404` if it does not exist.

### 17. `GET /subscriptions/{sub_id}/payments`

| Query parameter | Type | Description |
|---|---|---|
| `date_from`, `date_to` | date | `paid_at` range, inclusive. `date_from > date_to` → `422` |
| `sort` | string | `id`, `paid_at`, `amount`, `created_at`. Default `-paid_at` (newest first) |
| `limit`, `offset` | integer | Pagination |

Response `200`: page of payments (see 18). Response `404` if the subscription does not exist.

### 18. `POST /subscriptions/{sub_id}/payments`

Body (`amount` and `note` optional):

```json
{ "paid_at": "2026-10-15", "amount": 4990, "note": "Kaspi Gold" }
```

Response `201`:

```json
{
  "id": 1,
  "subscription_id": 1,
  "subscription_name": "Netflix",
  "paid_at": "2026-10-15",
  "amount": 4990.0,
  "currency": "KZT",
  "note": "Kaspi Gold",
  "created_at": "2026-11-17T09:00:00Z",
  "updated_at": "2026-11-17T09:00:00Z"
}
```

If `amount` is omitted, it is the subscription's current `price`.

Response `404`: subscription not found.
Response `409`: `{"detail": "Subscription 1 already has a payment on 2026-10-15"}`
Response `422`: `paid_at` in the future, `amount <= 0`, or
`{"detail": "paid_at must not be earlier than the subscription's start_date (2026-01-15)"}` /
`{"detail": "paid_at must not be later than the subscription's cancelled_at (2026-11-17)"}`

---

### 19. `GET /payments`

| Query parameter | Type | Description |
|---|---|---|
| `subscription_id` | integer | Only this subscription |
| `category_id` | integer | Only subscriptions of this category |
| `currency` | enum | Only subscriptions in this currency |
| `date_from`, `date_to` | date | `paid_at` range, inclusive. `date_from > date_to` → `422` |
| `min_amount` | decimal | `amount >=` value |
| `sort` | string | As in 17, default `-paid_at` |
| `limit`, `offset` | integer | Pagination |

Example: `GET /payments?category_id=1&date_from=2026-01-01&sort=amount`
Response `200`: page of payments.

### 20. `GET /payments/{payment_id}`

Response `200`: one payment. Response `404`: `{"detail": "Payment 999999 not found"}`

### 21. `PATCH /payments/{payment_id}`

Fix a payment: any of `paid_at`, `amount`, `note`. Same rules as in 18. The subscription cannot be changed.

```json
{ "amount": 5290, "note": "Discount" }
```

Response `200`: the updated payment. `404`, `409`, `422` as in 18.

### 22. `DELETE /payments/{payment_id}`

Response `204`, empty body. `404` if it does not exist.

## curl examples

```bash
# category, then a subscription in it
curl -X POST http://localhost:8000/categories -H "Content-Type: application/json" \
  -d '{"name": "Music"}'
curl -X POST http://localhost:8000/subscriptions -H "Content-Type: application/json" -d '{
  "category_id": 1, "name": "Spotify", "price": 1990, "currency": "KZT",
  "billing_cycle": "monthly", "start_date": "2026-01-31"
}'

# record payments and read the history
curl -X POST http://localhost:8000/subscriptions/1/payments -H "Content-Type: application/json" \
  -d '{"paid_at": "2026-10-31"}'
curl http://localhost:8000/subscriptions/1/payments
curl http://localhost:8000/categories/1/subscriptions

# update, cancel, delete
curl -X PATCH http://localhost:8000/subscriptions/1 -H "Content-Type: application/json" -d '{"active": false}'
curl -X DELETE http://localhost:8000/payments/1

# reports
curl http://localhost:8000/subscriptions/stats
curl "http://localhost:8000/subscriptions/upcoming?days=30"
```

## Postman

1. Start the stack: `docker compose up`.
2. In Postman: **Import** → select `postman_collection.json`.
3. Run the whole collection with **Run collection** (Collection Runner), or send the requests one by one in order.

The collection variable `baseUrl` is `http://localhost:8000`. Create requests save the new IDs into `{{catId}}`, `{{cat2Id}}`, `{{subId}}`, `{{sub2Id}}`, `{{payId}}`, `{{pay2Id}}`, so later requests work as a chain. Folder 5 deletes everything again, so the collection can be run repeatedly.

Every request has test assertions (status code and response body). Besides the happy path, the collection checks the error cases: duplicates (`409`), invalid bodies (`422`), unknown IDs (`404`) and the business rules between the tables.

| Folder | # | Request | Expected |
|---|---|---|---|
| 0. System | 1 | `GET /health` | `200` |
| 1. Categories | 2 | `POST /categories` (Streaming) | `201` |
| | 3 | `POST /categories` (Cloud) | `201` |
| | 4 | `POST /categories` duplicate name | `409` |
| | 5 | `POST /categories` invalid body | `422` |
| | 6 | `GET /categories` | `200` |
| | 7 | `GET /categories?q=stream&sort=-subscription_count` | `200` |
| | 8 | `GET /categories/{{catId}}` | `200` |
| | 9 | `GET /categories/999999` | `404` |
| | 10 | `PUT /categories/{{cat2Id}}` | `200` |
| | 11 | `PATCH /categories/{{catId}}` | `200` |
| 2. Subscriptions | 12 | `POST /subscriptions` (Netflix) | `201` |
| | 13 | `POST /subscriptions` (iCloud, yearly USD) | `201` |
| | 14 | duplicate name | `409` |
| | 15 | invalid body | `422` |
| | 16 | unknown `category_id` | `404` |
| | 17 | `GET /subscriptions` | `200` |
| | 18 | `GET /subscriptions` with filters + sort | `200` |
| | 19 | `GET /subscriptions/{{subId}}` | `200` |
| | 20 | `GET /subscriptions/999999` | `404` |
| | 21 | `GET /categories/{{catId}}/subscriptions` | `200` |
| | 22 | `PUT /subscriptions/{{subId}}` | `200` |
| 3. Payments | 23 | `POST /subscriptions/{{subId}}/payments` (default amount) | `201` |
| | 24 | `POST ...` (explicit amount) | `201` |
| | 25 | same day again | `409` |
| | 26 | before `start_date` | `422` |
| | 27 | future date, amount 0 | `422` |
| | 28 | `GET /subscriptions/{{subId}}/payments` | `200` |
| | 29 | `GET /subscriptions/{{subId}}` (payment totals) | `200` |
| | 30 | `GET /payments` with filters | `200` |
| | 31 | `GET /payments/{{payId}}` | `200` |
| | 32 | `PATCH /payments/{{payId}}` | `200` |
| | 33 | `DELETE /payments/{{pay2Id}}` | `204` |
| | 34 | `GET /payments/{{pay2Id}}` after delete | `404` |
| 4. Reports and business rules | 35 | `GET /subscriptions/stats` | `200` |
| | 36 | `GET /subscriptions/upcoming?days=31` | `200` |
| | 37 | change currency of a paid subscription | `409` |
| | 38 | `PATCH /subscriptions/{{subId}}` cancel | `200` |
| | 39 | `DELETE /categories/{{catId}}` (has subscriptions) | `409` |
| 5. Delete (cleanup) | 40 | `DELETE /subscriptions/{{subId}}` | `204` |
| | 41 | its payment is gone (cascade) | `404` |
| | 42 | `DELETE /subscriptions/{{sub2Id}}` | `204` |
| | 43 | `DELETE /categories/{{catId}}` | `204` |
| | 44 | `DELETE /categories/{{cat2Id}}` | `204` |
| | 45 | `GET /categories/{{catId}}` after delete | `404` |

From the command line: `npx newman run postman_collection.json`.

## Project structure

```
hw3/
├── backend/
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── requirements.txt
│   └── app/
│       ├── main.py                     # FastAPI app, startup (create tables), /health
│       ├── config.py                   # settings from environment variables
│       ├── database.py                 # SQLAlchemy engine and session
│       ├── models.py                   # Category, Subscription, Payment + relationships, computed fields
│       ├── schemas.py                  # Pydantic models: request/response, validation rules
│       ├── billing.py                  # next payment date, monthly/yearly cost (from the midterm)
│       └── routers/
│           ├── common.py               # 404/409 helpers, sorting, pagination, PATCH validation
│           ├── categories.py           # /categories and /categories/{id}/subscriptions
│           ├── subscriptions.py        # /subscriptions, stats, upcoming, /subscriptions/{id}/payments
│           └── payments.py             # /payments
├── docker-compose.yml
├── .env.example
├── .gitignore
├── postman_collection.json
└── README.md
```

## Environment variables

Defined in `.env` (template: `.env.example`).

| Variable | Used by | Example | Description |
|---|---|---|---|
| `POSTGRES_DB` | db, backend | `subtrack` | Database name |
| `POSTGRES_USER` | db, backend | `subtrack_user` | Database user |
| `POSTGRES_PASSWORD` | db, backend | `change_me` | Database password |
| `APP_NAME` | backend | `SubTrack API` | Title shown in Swagger |
| `APP_PORT` | compose | `8000` | Host port for the API |

## Useful commands

```bash
docker compose up --build           # build the backend image and start everything
docker compose ps                   # status of the containers (and health)
docker compose logs -f backend      # backend logs
docker compose down                 # stop and remove containers, KEEP data
docker compose down -v              # stop and DELETE the database volume
docker compose exec db psql -U subtrack_user -d subtrack -c "\d payments"
```
