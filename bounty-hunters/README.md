# Space Bounty Hunters API

REST API for space bounty hunters: a database of wanted criminals and a journal of hunting attempts.

**Stack:** FastAPI · SQLAlchemy 2 · PostgreSQL 16 · Docker Compose

## Project structure

```
bounty-hunters/
├── docker-compose.yml          # db (postgres:16-alpine) + backend (FastAPI)
├── .env.example                # copy to .env
├── db/init.sql                 # schema + seed data (6 criminals, 12 hunt logs)
├── postman_collection.json     # exported Postman collection (30 requests with tests)
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── main.py             # app, routers, /health
        ├── config.py           # settings from environment variables
        ├── database.py         # engine, session, get_db
        ├── models.py           # WantedCriminal, HuntLog (one-to-many)
        ├── schemas.py          # Pydantic request/response models, validation
        └── routers/
            ├── criminals.py    # GET list (filters + sort), GET details
            └── hunts.py        # full CRUD for hunt logs
```

## Run

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps            # both containers running, db is healthy
curl http://localhost:8001/health
```

- API: http://localhost:8001
- Swagger docs: http://localhost:8001/docs

## Database setup / import

`db/init.sql` creates both tables and fills them with seed data. It is mounted into
`/docker-entrypoint-initdb.d/`, so PostgreSQL **imports it automatically on the first start**
(when the `bounty_db_data` volume is empty).

Reset the database to the seed data:

```bash
docker compose down -v     
docker compose up -d
```

Import manually into a running database (also resets it):

```bash
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/init.sql
```

## Data model

**WantedCriminal** (`wanted_criminals`)

| Field | Type | Notes |
|---|---|---|
| id | int, PK | |
| name | string, nullable | real name, `null` if unknown |
| nickname | string | criminal alias |
| reward | int | bounty amount, ≥ 0 |
| last_latitude, last_longitude | float, nullable | last known coordinates (both set or both null) |
| last_location_note | text, nullable | last known location as a text note |
| difficulty | int | 1 to 10 (CHECK constraint) |
| armed, has_crew, escape_master | bool | |

**HuntLog** (`hunt_logs`)

| Field | Type | Notes |
|---|---|---|
| id | int, PK | |
| criminal_id | int, FK → wanted_criminals.id | must reference an existing criminal |
| success | bool | was the criminal captured |
| notes | text | encounter description, not empty |
| created_at | timestamptz | `DEFAULT now()`, set by the server only |

Relationship: one `WantedCriminal` → many `HuntLog` (`criminal.hunts` / `hunt.criminal`, `ON DELETE CASCADE`).

## Endpoints

### Wanted criminals

| Method | URL | Description |
|---|---|---|
| GET | `/api/criminals/` | List criminals |
| GET | `/api/criminals/{id}/` | Criminal details + hunt history |

Query parameters for the list (all optional, combined with AND):

| Parameter | Example | Meaning |
|---|---|---|
| `min_reward` | `5000` | reward ≥ value |
| `max_reward` | `1000000` | reward ≤ value |
| `armed`, `has_crew`, `escape_master` | `true` / `false` | filter by attribute |
| `sort` | `reward` / `-reward` | ascending / descending by reward |

```
GET /api/criminals/?min_reward=5000&armed=true&sort=-reward
```

### Hunt logs (journal)

| Method | URL | Description | Success code |
|---|---|---|---|
| GET | `/api/hunts/` | List logs, `?criminal_id=5` to filter | 200 |
| GET | `/api/hunts/{id}/` | One log | 200 |
| POST | `/api/hunts/` | Record a capture attempt | 201 |
| PATCH | `/api/hunts/{id}/` | Update `success` and/or `notes` | 200 |
| DELETE | `/api/hunts/{id}/` | Delete a log | 204 |

POST body:

```json
{
  "criminal_id": 3,
  "success": false,
  "notes": "Target escaped through an asteroid field."
}
```

### Error handling

| Situation | Code |
|---|---|
| Criminal / hunt log id not found | 404 |
| `?criminal_id=` of a non-existent criminal | 404 |
| POST with `criminal_id` of a non-existent criminal | 422 |
| Missing fields, wrong types, empty `notes` | 422 |
| Client sends `id` or `created_at` (unknown fields are rejected) | 422 |
| PATCH with empty body, `null` values, or `criminal_id` | 422 |
| Invalid `sort` value, non-boolean filter, non-numeric id | 422 |
| `min_reward` > `max_reward` | 400 |

## Postman

1. Postman → **Import** → `postman_collection.json`.
2. Collection variable `baseUrl` = `http://localhost:8001`.
3. Run the requests top to bottom, or **Run collection**. The POST request saves the new id into
   `{{huntId}}`, which the GET / PATCH / DELETE requests use.

The collection has two folders:
- **Wanted Criminals**: listing, every filter, both sort orders, details, invalid requests.
- **Hunt Logs (CRUD)**: list, filter, create, read, update, delete, invalid requests.

Every request has tests (status code + response checks). Run from the command line:

```bash
npx newman run postman_collection.json
```

For a clean run, reset the database first (`docker compose down -v && docker compose up -d`).