# Real-Time Event Pipeline

Event ingestion, routing, and real-time delivery for educational platforms. Publish events via REST or WebSocket, subscribe to filtered event streams, and query event history — all backed by async Python and persistent storage.

![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.129-green?logo=fastapi&logoColor=white)
![WebSocket](https://img.shields.io/badge/WebSocket-Real--time-orange)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Tests](https://img.shields.io/badge/Tests-45_passing-purple)

## Features

- **REST + WebSocket Ingestion** — publish events via HTTP or high-frequency WebSocket connections
- **Pub/Sub Routing** — subscribers receive matching events in real time via WebSocket
- **Flexible Filtering** — subscribe by event type, session ID, or user ID
- **Event Persistence** — all events stored in SQLite with indexed queries
- **Live Statistics** — monitor throughput, event counts, and active subscribers
- **Event Replay** — query historical events with time-range and type filters
- **API Versioning** — `/api/v1/` prefix with backwards-compatible unversioned routes
- **Authentication** — opt-in API key auth via `X-API-Key` header
- **Rate Limiting** — configurable per-endpoint rate limits
- **Security Hardened** — security headers, input validation, bounded queues, sanitized errors
- **Health Checks** — `/health` and `/readiness` endpoints for load balancers
- **Docker Ready** — Dockerfile and docker-compose.yml included

## Architecture

```
┌──────────────────┐         ┌───────────────────────────────┐         ┌──────────────────┐
│   PRODUCERS      │         │     REAL-TIME EVENT PIPELINE  │         │   CONSUMERS      │
│                  │         │                               │         │                  │
│  Quiz Engine     │         │  ┌─────────┐   ┌──────────┐  │         │  Teacher         │
│  Student App     │────────►│  │ REST API │──►│  Event   │  │────────►│  Dashboard       │
│  Timer Service   │  REST   │  └─────────┘   │  Router  │  │   WS    │  Analytics       │
│                  │────────►│  ┌─────────┐   │ (Pub/Sub)│  │────────►│  Progress        │
│                  │   WS    │  │ WS API  │──►│          │  │         │  Tracker         │
│                  │         │  └─────────┘   └────┬─────┘  │         │                  │
│                  │         │                     │        │         │                  │
│                  │         │              ┌──────▼──────┐ │         │                  │
│                  │         │              │   SQLite    │ │         │                  │
│                  │         │              │ (Persistence)│ │         │                  │
│                  │         │              └─────────────┘ │         │                  │
└──────────────────┘         └───────────────────────────────┘         └──────────────────┘
```

**How it works:**
1. Producers publish events via `POST /api/v1/events` or `/ws/publish`
2. Events are persisted to SQLite and pushed to the bounded async queue
3. The EventRouter matches events against subscriber filters
4. Matching events are delivered to subscribers over WebSocket in real time

## Quick Start

```bash
# Clone and setup
git clone https://github.com/woodstocksoftware/realtime-event-pipeline.git
cd realtime-event-pipeline
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start the server
python -m uvicorn src.server:app --reload --port 8001
```

The API is now running at `http://localhost:8001`. Interactive docs at `http://localhost:8001/docs`.

### Or use Docker

```bash
docker compose up --build
```

### Publish an Event

```bash
curl -X POST http://localhost:8001/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "quiz_started",
    "source": "quiz_engine",
    "session_id": "session-123",
    "user_id": "student-456",
    "payload": {"quiz_id": "math-101", "total_questions": 20}
  }'
```

### Subscribe to Events

```javascript
const ws = new WebSocket('ws://localhost:8001/ws/subscribe');

ws.onopen = () => {
  // Step 1: Send filter configuration
  ws.send(JSON.stringify({
    event_types: ['quiz_started', 'answer_submitted', 'quiz_completed'],
    session_id: 'session-123'
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  // Step 2: Handle subscription confirmation
  if (data.status === 'subscribed') {
    console.log('Subscribed:', data.subscriber_id);
    return;
  }

  // Step 3: Ignore keepalive messages (sent every 30s)
  if (data.type === 'keepalive') return;

  // Step 4: Handle events
  console.log(`[${data.event_type}]`, data.payload);
};

// Optional: Update filters dynamically
ws.send(JSON.stringify({
  type: 'update_filters',
  filters: { session_id: 'new-session-789' }
}));

// Optional: Ping/pong for connection health
ws.send(JSON.stringify({ type: 'ping' }));
// Server responds with: { type: 'pong' }
```

## Configuration

All settings are configured via environment variables. Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8001` | Server port |
| `DATABASE_PATH` | `data/events.db` | SQLite file location |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `REQUIRE_AUTH` | `false` | Enable API key authentication |
| `API_KEY` | (empty) | API key when auth is enabled |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `MAX_QUEUE_SIZE` | `10000` | Event queue bound (backpressure) |
| `MAX_SUBSCRIBERS` | `5000` | Max concurrent WebSocket subscribers |
| `MAX_WS_MESSAGE_BYTES` | `1048576` | Max WebSocket message size (1 MB) |
| `MAX_PAYLOAD_KEYS` | `50` | Max keys in event payload |
| `RATE_LIMIT_PUBLISH` | `200/minute` | Rate limit for publish endpoints |
| `RATE_LIMIT_QUERY` | `600/minute` | Rate limit for query endpoints |
| `RATE_LIMIT_ADMIN` | `10/minute` | Rate limit for admin endpoints |

### Authentication

Set `REQUIRE_AUTH=true` and `API_KEY=your-secret-key` to enforce authentication:

```bash
# REST — pass via header
curl -H "X-API-Key: your-secret-key" http://localhost:8001/api/v1/events

# WebSocket — pass via query parameter
ws://localhost:8001/ws/subscribe?api_key=your-secret-key
```

## Event Schema

### Publishing (Input)

| Field | Type | Required | Validation | Description |
|-------|------|----------|------------|-------------|
| `event_type` | string | Yes | Must be a registered type | Event type (e.g., `quiz_started`) |
| `source` | string | Yes | 1-100 chars, alphanumeric/dash/underscore | Source system (e.g., `quiz_engine`) |
| `session_id` | string | No | Max 200 chars | Quiz/test session identifier |
| `user_id` | string | No | Max 200 chars | Student/user identifier |
| `payload` | object | No | Max 50 keys, max 64 KB | Event-specific data |

### Response (Output)

```json
{
  "id": "evt_a1b2c3d4e5f6",
  "event_type": "answer_submitted",
  "source": "quiz_engine",
  "session_id": "session-123",
  "user_id": "student-456",
  "payload": {
    "question_id": "q-42",
    "answer": "B",
    "time_spent_ms": 12500
  },
  "timestamp": "2026-01-15T10:30:45Z"
}
```

## Event Types

| Category | Event Type | Description |
|----------|-----------|-------------|
| **Quiz** | `quiz_started` | Student began a quiz session |
| | `quiz_completed` | Student submitted/finished the quiz |
| | `quiz_timeout` | Quiz timer expired |
| **Answer** | `answer_submitted` | Student submitted an answer |
| | `answer_changed` | Student revised their answer |
| **Navigation** | `question_viewed` | Student navigated to a question |
| | `question_skipped` | Student skipped a question |
| **Timer** | `timer_started` | Session timer began |
| | `timer_tick` | Timer update (every second) |
| | `timer_warning` | Warning threshold reached |
| **Progress** | `mastery_updated` | Student mastery level changed |
| | `learning_gap_detected` | Learning gap identified |
| **System** | `session_created` | New session initialized |
| | `session_ended` | Session terminated |
| | `error_occurred` | System error recorded |

Event types are validated on publish. Unknown types return `422 Unprocessable Entity`.

## API Reference

### Monitoring

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check (`{"status": "ok"}`) |
| `GET` | `/readiness` | Readiness check (DB + router status) |

### REST Endpoints (v1)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/v1/events` | Yes* | Publish an event (returns `201`) |
| `GET` | `/api/v1/events` | Yes* | Query events (filters: `event_type`, `session_id`, `user_id`, `limit`, `since`) |
| `GET` | `/api/v1/events/{id}` | Yes* | Get a specific event by ID |
| `GET` | `/api/v1/stats` | Yes* | Pipeline statistics |
| `GET` | `/api/v1/event-types` | No | List all registered event types |
| `DELETE` | `/api/v1/events` | Admin* | Clear events (optional `before` timestamp) |

*Auth only enforced when `REQUIRE_AUTH=true`.

### WebSocket Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `/ws/publish` | Yes* | Send JSON events, receive `{status, event_id}` confirmations |
| `/ws/subscribe` | Yes* | Send filter config, receive matching events in real time |

### WebSocket Subscribe Protocol

1. **Connect** to `/ws/subscribe`
2. **Send** filter config: `{"event_types": [...], "session_id": "...", "user_id": "..."}`
3. **Receive** confirmation: `{"status": "subscribed", "subscriber_id": "...", "filters": {...}}`
4. **Receive** matching events as they're published
5. **Send** `{"type": "ping"}` to receive `{"type": "pong"}` (connection health)
6. **Send** `{"type": "update_filters", "filters": {...}}` to change filters
7. **Receive** `{"type": "keepalive"}` every 30s if idle

### Query Examples

```bash
# Recent events (default limit: 100)
curl "http://localhost:8001/api/v1/events?limit=10"

# Filter by type and session
curl "http://localhost:8001/api/v1/events?event_type=answer_submitted&session_id=session-123"

# Events since a timestamp
curl "http://localhost:8001/api/v1/events?since=2026-01-15T10:00:00Z"

# Pipeline statistics
curl "http://localhost:8001/api/v1/stats"
```

## Usage: Assessment Platform Integration

```python
import httpx

PIPELINE_URL = "http://localhost:8001/api/v1"

async def publish_quiz_event(session_id: str, user_id: str, event_type: str, payload: dict):
    """Publish an event from the quiz engine to the pipeline."""
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{PIPELINE_URL}/events", json={
            "event_type": event_type,
            "source": "quiz_engine",
            "session_id": session_id,
            "user_id": user_id,
            "payload": payload,
        })
        return response.json()

# Start a quiz
await publish_quiz_event("session-123", "student-456", "quiz_started", {
    "quiz_id": "math-101",
    "total_questions": 20,
})

# Record an answer
await publish_quiz_event("session-123", "student-456", "answer_submitted", {
    "question_id": "q-1",
    "answer": "B",
    "correct": True,
    "time_spent_ms": 8500,
})

# Complete the quiz
await publish_quiz_event("session-123", "student-456", "quiz_completed", {
    "score": 85,
    "total_questions": 20,
    "correct_answers": 17,
    "duration_seconds": 420,
})
```

## Part of the Ed-Tech Platform Suite

| Component | Description |
|-----------|-------------|
| [Question Bank MCP](https://github.com/woodstocksoftware/question-bank-mcp) | Question management and selection |
| [Student Progress Tracker](https://github.com/woodstocksoftware/student-progress-tracker) | Performance analytics and tracking |
| [Simple Quiz Engine](https://github.com/woodstocksoftware/simple-quiz-engine) | Real-time quiz delivery |
| [Learning Curriculum Builder](https://github.com/woodstocksoftware/learning-curriculum-builder) | Curriculum design and adaptation |
| **Real-Time Event Pipeline** | **Central event bus (this repo)** |

## Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=src
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes with tests
4. Run linting (`ruff check src/ tests/`)
5. Submit a pull request

## License

MIT

---

Built by [Jim Williams](https://linkedin.com/in/woodstocksoftware) | [GitHub](https://github.com/woodstocksoftware)
