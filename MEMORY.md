# MEMORY.md

## Current State

- **Status:** Active — production-ready event pipeline (v2.0.0)
- **Source:** 6 modules in `src/` (config, models, database, router, middleware, server)
- **Database:** SQLite at configurable path (default `data/events.db`, gitignored)
- **Test count:** 45 tests in `tests/test_server.py`
- **Dependencies:** FastAPI, Uvicorn, Pydantic, websockets, slowapi, python-dateutil (all pinned)
- **Port:** 8001 (configurable via `PORT` env var)

## Architecture

- **config.py** — all settings from environment variables
- **models.py** — Pydantic models with field validators (event_type whitelist, source pattern, payload size limits)
- **database.py** — SQLite layer with file permission hardening
- **router.py** — EventRouter with bounded queue (`MAX_QUEUE_SIZE`) and subscriber cap (`MAX_SUBSCRIBERS`)
- **middleware.py** — security headers, API key auth (`X-API-Key`), WebSocket connection limiter
- **server.py** — FastAPI app with `/api/v1/` versioned routes + backwards-compatible unversioned aliases

## Security Features

- API key authentication (opt-in via `REQUIRE_AUTH=true`)
- Rate limiting on all endpoints (slowapi)
- Security headers (CSP, X-Frame-Options, nosniff, XSS protection, HSTS)
- CORS restricted to configured origins
- Input validation (event_type whitelist, source regex, payload size/key limits)
- WebSocket: origin-aware auth, message size limits, per-IP connection limits
- Sanitized error responses (no stack traces leaked)
- SQLite file permissions restricted to owner (600)
- Bounded event queue and subscriber dictionary
- Structured logging (no print statements)

## Integration with Ed-Tech Platform

This pipeline is the **central event bus** for the adaptive testing platform suite:

| Service | Role |
|---------|------|
| [Simple Quiz Engine](https://github.com/woodstocksoftware/simple-quiz-engine) | **Producer** — publishes quiz_started, answer_submitted, quiz_completed |
| [Student Progress Tracker](https://github.com/woodstocksoftware/student-progress-tracker) | **Consumer** — subscribes to answer/progress events for analytics |
| [Question Bank MCP](https://github.com/woodstocksoftware/question-bank-mcp) | **Producer** — publishes question selection events |
| [Learning Curriculum Builder](https://github.com/woodstocksoftware/learning-curriculum-builder) | **Consumer** — subscribes to mastery/progress events |
