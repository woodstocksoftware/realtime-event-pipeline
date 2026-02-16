# CLAUDE.md

## Project Overview

Real-Time Event Pipeline — an async event pub/sub system for routing educational platform events via REST and WebSocket APIs.

## Tech Stack

- **Language:** Python 3.12+
- **Framework:** FastAPI 0.109+ (ASGI)
- **Server:** Uvicorn
- **WebSocket:** `websockets` 12.0+
- **Validation:** Pydantic 2.0+
- **Database:** SQLite (file-based, `data/events.db`)
- **Concurrency:** asyncio (Queue-based event processing)

## Architecture

Single-server pub/sub event router:

```
Producers → REST/WebSocket → EventRouter → SQLite (persistence)
                                  ↓
                            WebSocket → Subscribers
```

- **EventRouter** (`src/server.py:113`) — core pub/sub engine with async queue, subscriber registry, and filter matching
- **REST API** — CRUD endpoints for events, stats, event types
- **WebSocket** — `/ws/publish` for high-frequency ingestion, `/ws/subscribe` for real-time delivery
- **Database** — 3 tables: `events`, `subscriptions`, `event_stats` with indexes on type, session, timestamp, user

## Commands

```bash
# Install
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run server
python -m uvicorn src.server:app --reload --port 8001

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/
```

## Event Schema

**Publishing (POST /events):**
```json
{
  "event_type": "quiz_started",
  "source": "quiz_engine",
  "session_id": "session-123",
  "user_id": "student-456",
  "payload": {"quiz_id": "demo-quiz"}
}
```

**Response:**
```json
{
  "id": "evt_a1b2c3d4e5f6",
  "event_type": "quiz_started",
  "source": "quiz_engine",
  "session_id": "session-123",
  "user_id": "student-456",
  "payload": {"quiz_id": "demo-quiz"},
  "timestamp": "2026-01-15T10:30:00Z"
}
```

## Event Types

| Category | Types |
|----------|-------|
| Quiz | `quiz_started`, `quiz_completed`, `quiz_timeout` |
| Answer | `answer_submitted`, `answer_changed` |
| Navigation | `question_viewed`, `question_skipped` |
| Timer | `timer_started`, `timer_tick`, `timer_warning` |
| Progress | `mastery_updated`, `learning_gap_detected` |
| System | `session_created`, `session_ended`, `error_occurred` |

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/events` | Publish event |
| GET | `/events` | Query events (filters: event_type, session_id, user_id, limit, since) |
| GET | `/events/{id}` | Get single event |
| GET | `/stats` | Pipeline statistics |
| GET | `/event-types` | List registered event types |
| DELETE | `/events` | Clear events (optional `before` timestamp) |
| WS | `/ws/publish` | High-frequency publish |
| WS | `/ws/subscribe` | Subscribe with filters |

## Integration

Part of the ed-tech platform suite. Producers (quiz engine, student app) publish events; consumers (dashboards, analytics, progress tracker) subscribe via WebSocket.

## Key Files

- `src/server.py` — entire application (models, router, API, WebSocket handlers)
- `tests/test_server.py` — API and router tests
- `data/events.db` — SQLite database (gitignored)
