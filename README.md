# Real-Time Event Pipeline

Event ingestion, routing, and processing for the ed-tech platform.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green)
![WebSocket](https://img.shields.io/badge/WebSocket-Real--time-orange)

## Features

- **Event Ingestion** - REST and WebSocket endpoints
- **Pub/Sub Routing** - Real-time event delivery to subscribers
- **Filtering** - Subscribe by event type, session, or user
- **Persistence** - SQLite storage for event history
- **Analytics** - Event statistics and querying

## Architecture
```
Producers                    Pipeline                     Consumers
─────────                    ────────                     ─────────
Quiz Engine ──┐                                      ┌── Teacher Dashboard
              │         ┌─────────────────┐          │
Student App ──┼────────►│  Event Router   │─────────►├── Analytics Service
              │         │  (FastAPI + WS) │          │
Timer Service─┘         └────────┬────────┘          └── Progress Tracker
                                 │
                                 ▼
                         ┌──────────────┐
                         │   SQLite     │
                         └──────────────┘
```

## Quick Start
```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn src.server:app --reload --port 8001
```

## API Endpoints

### REST

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/events` | POST | Publish an event |
| `/events` | GET | Query events with filters |
| `/events/{id}` | GET | Get specific event |
| `/stats` | GET | Pipeline statistics |
| `/event-types` | GET | List supported event types |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `/ws/publish` | High-frequency event publishing |
| `/ws/subscribe` | Subscribe to real-time events |

## Event Types

| Type | Description |
|------|-------------|
| `quiz_started` | Student started a quiz |
| `quiz_completed` | Quiz submitted/finished |
| `answer_submitted` | Answer recorded |
| `question_viewed` | Question displayed |
| `timer_tick` | Timer update |
| `mastery_updated` | Mastery level changed |

## Usage Examples

### Publish Event (REST)
```bash
curl -X POST http://localhost:8001/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "quiz_started",
    "source": "quiz_engine",
    "session_id": "session-123",
    "user_id": "student-456",
    "payload": {"quiz_id": "demo-quiz"}
  }'
```

### Subscribe (WebSocket)
```javascript
const ws = new WebSocket('ws://localhost:8001/ws/subscribe');

ws.onopen = () => {
  // Subscribe to specific events
  ws.send(JSON.stringify({
    event_types: ['quiz_started', 'answer_submitted'],
    session_id: 'session-123'
  }));
};

ws.onmessage = (event) => {
  console.log('Event:', JSON.parse(event.data));
};
```

### Query Events
```bash
# Get recent events
curl "http://localhost:8001/events?limit=10"

# Filter by type and session
curl "http://localhost:8001/events?event_type=answer_submitted&session_id=session-123"
```

## Part of Ed-Tech Suite

| Component | Repository |
|-----------|------------|
| [Question Bank MCP](https://github.com/woodstocksoftware/question-bank-mcp) | Question management |
| [Student Progress Tracker](https://github.com/woodstocksoftware/student-progress-tracker) | Performance analytics |
| [Simple Quiz Engine](https://github.com/woodstocksoftware/simple-quiz-engine) | Real-time quizzes |
| [Learning Curriculum Builder](https://github.com/woodstocksoftware/learning-curriculum-builder) | Curriculum design |
| **Real-Time Event Pipeline** | Event routing |

## License

MIT

---

Built by [Jim Williams](https://linkedin.com/in/woodstocksoftware) | [GitHub](https://github.com/woodstocksoftware)
