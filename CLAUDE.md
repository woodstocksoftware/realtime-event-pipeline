# CLAUDE.md

## Project Overview

Real-Time Event Pipeline — an async event pub/sub system for routing educational platform events via REST and WebSocket APIs.

## Tech Stack

- **Language:** Python 3.12+
- **Framework:** FastAPI (ASGI)
- **Server:** Uvicorn
- **WebSocket:** `websockets`
- **Validation:** Pydantic 2.x with field validators
- **Database:** SQLite (file-based, configurable path)
- **Rate Limiting:** slowapi
- **Auth:** API key via `X-API-Key` header (opt-in)
- **Concurrency:** asyncio (bounded queue event processing)

## Architecture

```
src/
  config.py      — env var configuration
  models.py      — Pydantic models + event type registry + input validation
  database.py    — SQLite operations (init, insert, query, stats, delete)
  router.py      — EventRouter (bounded pub/sub with subscriber limits)
  middleware.py   — security headers, API key auth, WS connection limiter
  server.py      — FastAPI app, endpoints (/api/v1/...), WebSocket handlers
```

```
Producers → REST/WebSocket → EventRouter → SQLite (persistence)
                                  ↓
                            WebSocket → Subscribers
```

## Commands

```bash
# Install
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run server
python -m uvicorn src.server:app --reload --port 8001

# Run tests
pytest tests/ -v

# Lint + format
ruff check src/ tests/
ruff format src/ tests/

# Docker
docker compose up --build
```

## Configuration

All settings via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8001` | Server port |
| `DATABASE_PATH` | `data/events.db` | SQLite file location |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `REQUIRE_AUTH` | `false` | Enable API key authentication |
| `API_KEY` | (empty) | API key when auth is enabled |
| `LOG_LEVEL` | `INFO` | Logging level |
| `MAX_QUEUE_SIZE` | `10000` | Event queue bound |
| `MAX_SUBSCRIBERS` | `5000` | Max WebSocket subscribers |
| `MAX_WS_MESSAGE_BYTES` | `1048576` | Max WebSocket message size (1 MB) |
| `MAX_PAYLOAD_KEYS` | `50` | Max keys in event payload |
| `RATE_LIMIT_PUBLISH` | `200/minute` | Rate limit for publish endpoints |

## API Endpoints

All REST endpoints are available at `/api/v1/...` (preferred) and `/...` (backwards-compatible).

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | No | Health check |
| GET | `/readiness` | No | Readiness check (DB connectivity) |
| POST | `/api/v1/events` | Yes* | Publish event (returns 201) |
| GET | `/api/v1/events` | Yes* | Query events with filters |
| GET | `/api/v1/events/{id}` | Yes* | Get single event |
| GET | `/api/v1/stats` | Yes* | Pipeline statistics |
| GET | `/api/v1/event-types` | No | List registered event types |
| DELETE | `/api/v1/events` | Admin* | Clear events |
| WS | `/ws/publish` | Yes* | High-frequency publish |
| WS | `/ws/subscribe` | Yes* | Subscribe with filters |

*Auth only enforced when `REQUIRE_AUTH=true`.

## Event Types

15 registered types: `quiz_started`, `quiz_completed`, `quiz_timeout`, `answer_submitted`, `answer_changed`, `question_viewed`, `question_skipped`, `timer_started`, `timer_tick`, `timer_warning`, `mastery_updated`, `learning_gap_detected`, `session_created`, `session_ended`, `error_occurred`.

Event types are validated on publish — unknown types are rejected with 422.

## Key Files

- `src/server.py` — FastAPI app, all endpoints and WebSocket handlers
- `src/config.py` — all configuration from env vars
- `src/models.py` — Pydantic models with validation, event type registry
- `src/database.py` — SQLite operations
- `src/router.py` — EventRouter (pub/sub engine)
- `src/middleware.py` — security headers, auth, WS limiter
- `tests/test_server.py` — 45 tests (API, auth, validation, security, WebSocket)
