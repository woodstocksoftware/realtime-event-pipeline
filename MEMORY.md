# MEMORY.md

## Current State

- **Status:** Active — functional pub/sub event pipeline
- **Source:** Single file (`src/server.py`, ~560 LOC)
- **Database:** SQLite at `data/events.db` (gitignored)
- **Test count:** Unit and integration tests in `tests/test_server.py`
- **Dependencies:** FastAPI, Uvicorn, Pydantic, websockets, python-dateutil
- **Port:** 8001 (default)

## Architecture

- EventRouter class manages in-memory subscriber registry + async queue
- Events persisted to SQLite on publish, then routed to matching WebSocket subscribers
- Filtering by event_type, session_id, user_id
- 15 registered event types across 6 categories (quiz, answer, navigation, timer, progress, system)

## Integration with Ed-Tech Platform

This pipeline is the **central event bus** for the adaptive testing platform suite:

| Service | Role | Integration |
|---------|------|-------------|
| [Simple Quiz Engine](https://github.com/woodstocksoftware/simple-quiz-engine) | **Producer** — publishes quiz_started, answer_submitted, quiz_completed events |
| [Student Progress Tracker](https://github.com/woodstocksoftware/student-progress-tracker) | **Consumer** — subscribes to answer/progress events for analytics |
| [Question Bank MCP](https://github.com/woodstocksoftware/question-bank-mcp) | **Producer** — publishes question selection events |
| [Learning Curriculum Builder](https://github.com/woodstocksoftware/learning-curriculum-builder) | **Consumer** — subscribes to mastery/progress events for curriculum adaptation |

### Data Flow

```
Quiz Engine → POST /events (quiz_started) → EventRouter → WS → Progress Tracker
Student App → POST /events (answer_submitted) → EventRouter → WS → Dashboard
Timer Service → WS /ws/publish (timer_tick) → EventRouter → WS → Quiz UI
```

## Known Considerations

- Subscriber registry is in-memory only (lost on restart)
- SQLite is single-writer; suitable for moderate throughput
- CORS is wide open (`*`) — tighten for production
- No authentication on endpoints
