# Real-Time Event Pipeline

Event ingestion, routing, and real-time delivery for educational platforms. Publish events via REST or WebSocket, subscribe to filtered event streams, and query event history — all backed by async Python and persistent storage.

![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green?logo=fastapi&logoColor=white)
![WebSocket](https://img.shields.io/badge/WebSocket-Real--time-orange)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Tests](https://img.shields.io/badge/Tests-pytest-purple)

## Features

- **REST + WebSocket Ingestion** — publish events via HTTP or high-frequency WebSocket connections
- **Pub/Sub Routing** — subscribers receive matching events in real time via WebSocket
- **Flexible Filtering** — subscribe by event type, session ID, or user ID
- **Event Persistence** — all events stored in SQLite with indexed queries
- **Live Statistics** — monitor throughput, event counts, and active subscribers
- **Event Replay** — query historical events with time-range and type filters
- **15 Event Types** — quiz, answer, navigation, timer, progress, and system events

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
1. Producers publish events via `POST /events` or `/ws/publish`
2. Events are persisted to SQLite and pushed to the async processing queue
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

### Publish an Event

```bash
curl -X POST http://localhost:8001/events \
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
  ws.send(JSON.stringify({
    event_types: ['quiz_started', 'answer_submitted', 'quiz_completed'],
    session_id: 'session-123'
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`[${data.event_type}]`, data.payload);
};
```

## Event Schema

### Publishing (Input)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_type` | string | Yes | Event type (e.g., `quiz_started`) |
| `source` | string | Yes | Originating system (e.g., `quiz_engine`) |
| `session_id` | string | No | Quiz/test session identifier |
| `user_id` | string | No | Student/user identifier |
| `payload` | object | No | Event-specific data (default: `{}`) |

### Response (Output)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Generated ID (`evt_` + 12-char hex) |
| `event_type` | string | Event type |
| `source` | string | Originating system |
| `session_id` | string \| null | Session identifier |
| `user_id` | string \| null | User identifier |
| `payload` | object | Event-specific data |
| `timestamp` | string | ISO 8601 UTC timestamp |

### Example Response

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
    "time_spent_ms": 12500,
    "confidence": "high"
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

## API Reference

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/events` | Publish an event |
| `GET` | `/events` | Query events (filters: `event_type`, `session_id`, `user_id`, `limit`, `since`) |
| `GET` | `/events/{id}` | Get a specific event by ID |
| `GET` | `/stats` | Pipeline statistics (totals, by-type counts, active subscribers) |
| `GET` | `/event-types` | List all registered event types |
| `DELETE` | `/events` | Clear events (optional `before` timestamp) |

### WebSocket Endpoints

| Endpoint | Direction | Description |
|----------|-----------|-------------|
| `/ws/publish` | Client → Server | Send JSON events, receive `{status, event_id}` confirmations |
| `/ws/subscribe` | Server → Client | Send filter config, receive matching events in real time |

### Query Examples

```bash
# Recent events (default limit: 100)
curl "http://localhost:8001/events?limit=10"

# Filter by type and session
curl "http://localhost:8001/events?event_type=answer_submitted&session_id=session-123"

# Events since a timestamp
curl "http://localhost:8001/events?since=2026-01-15T10:00:00Z"

# Pipeline statistics
curl "http://localhost:8001/stats"
```

## Usage: Assessment Platform Integration

Connect a quiz engine as a producer and a dashboard as a consumer:

```python
import httpx

async def publish_quiz_event(session_id: str, user_id: str, event_type: str, payload: dict):
    """Publish an event from the quiz engine to the pipeline."""
    async with httpx.AsyncClient() as client:
        response = await client.post("http://localhost:8001/events", json={
            "event_type": event_type,
            "source": "quiz_engine",
            "session_id": session_id,
            "user_id": user_id,
            "payload": payload
        })
        return response.json()

# Start a quiz
await publish_quiz_event("session-123", "student-456", "quiz_started", {
    "quiz_id": "math-101",
    "total_questions": 20
})

# Record an answer
await publish_quiz_event("session-123", "student-456", "answer_submitted", {
    "question_id": "q-1",
    "answer": "B",
    "correct": True,
    "time_spent_ms": 8500
})

# Complete the quiz
await publish_quiz_event("session-123", "student-456", "quiz_completed", {
    "score": 85,
    "total_questions": 20,
    "correct_answers": 17,
    "duration_seconds": 420
})
```

### Real-Time Dashboard Subscriber

```javascript
const ws = new WebSocket('ws://localhost:8001/ws/subscribe');

ws.onopen = () => {
  // Subscribe to all quiz progress for a class
  ws.send(JSON.stringify({
    event_types: ['quiz_started', 'answer_submitted', 'quiz_completed', 'mastery_updated']
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch (data.event_type) {
    case 'quiz_started':
      addStudentToLiveBoard(data.user_id, data.payload);
      break;
    case 'answer_submitted':
      updateStudentProgress(data.user_id, data.payload);
      break;
    case 'quiz_completed':
      showStudentResult(data.user_id, data.payload);
      break;
  }
};

// Update filters dynamically
ws.send(JSON.stringify({
  type: 'update_filters',
  filters: { session_id: 'new-session-789' }
}));
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
