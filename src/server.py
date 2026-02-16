"""
Real-Time Event Pipeline

Captures, routes, and processes events for the ed-tech platform.
"""

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from src import config
from src.database import (
    delete_events,
    get_event_by_id,
    init_database,
    insert_event,
    query_events,
)
from src.database import (
    get_stats as db_get_stats,
)
from src.middleware import (
    SecurityHeadersMiddleware,
    require_admin,
    require_auth,
    verify_ws_api_key,
    ws_limiter,
)
from src.models import EVENT_TYPES, Event, EventResponse
from src.router import EventRouter

logger = logging.getLogger(__name__)

# ── Logging Setup ───────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

# ── Database Init ───────────────────────────────────────────────

init_database()

# ── Router Instance ─────────────────────────────────────────────

event_router = EventRouter()

# ── Rate Limiter ────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

# ── App Lifecycle ───────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    event_router.start()
    logger.info("Event Pipeline started (v%s)", config.VERSION)
    yield
    event_router.stop()
    logger.info("Event Pipeline stopped")


# ── FastAPI App ─────────────────────────────────────────────────

app = FastAPI(
    title="Real-Time Event Pipeline",
    description="Event ingestion, routing, and processing for ed-tech platform",
    version=config.VERSION,
    lifespan=lifespan,
    debug=config.DEBUG,
)

app.state.limiter = limiter

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
    )


# ── Health Endpoints ────────────────────────────────────────────


@app.get("/health", tags=["monitoring"])
async def health():
    """Health check for load balancers."""
    return {"status": "ok", "service": "event-pipeline", "version": config.VERSION}


@app.get("/readiness", tags=["monitoring"])
async def readiness():
    """Readiness check — verifies database connectivity."""
    from src.database import get_connection

    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
        return {
            "ready": True,
            "database": "connected",
            "router": event_router.get_stats(),
        }
    except Exception as e:
        logger.error("Readiness check failed: %s", e)
        return JSONResponse(
            status_code=503,
            content={"ready": False, "database": "disconnected"},
        )


# ── Versioned API Router ───────────────────────────────────────

v1 = APIRouter(prefix="/api/v1")


# ── Event Endpoints ─────────────────────────────────────────────


@v1.post("/events", status_code=201, response_model=EventResponse)
@limiter.limit(config.RATE_LIMIT_PUBLISH)
async def publish_event(request: Request, event: Event, _=Depends(require_auth)):
    """Publish an event to the pipeline."""
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    insert_event(
        event_id=event_id,
        event_type=event.event_type,
        source=event.source,
        session_id=event.session_id,
        user_id=event.user_id,
        payload=event.payload,
        timestamp=timestamp,
    )

    event_response = EventResponse(
        id=event_id,
        event_type=event.event_type,
        source=event.source,
        session_id=event.session_id,
        user_id=event.user_id,
        payload=event.payload,
        timestamp=timestamp,
    )

    if not await event_router.publish(event_response):
        logger.warning("Queue full — event %s persisted but not routed live", event_id)

    return event_response


@v1.get("/events", response_model=List[EventResponse])
@limiter.limit(config.RATE_LIMIT_QUERY)
async def get_events(
    request: Request,
    event_type: Optional[str] = Query(None, max_length=50, description="Filter by event type"),
    session_id: Optional[str] = Query(None, max_length=200, description="Filter by session"),
    user_id: Optional[str] = Query(None, max_length=200, description="Filter by user"),
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    since: Optional[str] = Query(None, max_length=30, description="ISO 8601 timestamp"),
    _=Depends(require_auth),
):
    """Query persisted events with optional filters."""
    if since:
        try:
            datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid ISO 8601 timestamp for 'since'")

    return query_events(
        event_type=event_type,
        session_id=session_id,
        user_id=user_id,
        since=since,
        limit=limit,
    )


@v1.get("/events/{event_id}", response_model=EventResponse)
@limiter.limit(config.RATE_LIMIT_QUERY)
async def get_event(request: Request, event_id: str, _=Depends(require_auth)):
    """Get a specific event by ID."""
    event = get_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@v1.get("/stats")
@limiter.limit(config.RATE_LIMIT_QUERY)
async def get_stats(request: Request, _=Depends(require_auth)):
    """Get pipeline statistics."""
    stats = db_get_stats()
    stats["router"] = event_router.get_stats()
    return stats


@v1.delete("/events")
@limiter.limit(config.RATE_LIMIT_ADMIN)
async def clear_events(
    request: Request,
    before: Optional[str] = Query(None, description="Clear events before this ISO 8601 timestamp"),
    _=Depends(require_admin),
):
    """Clear events (admin endpoint)."""
    if before:
        try:
            datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid ISO 8601 timestamp for 'before'")

    deleted = delete_events(before)
    logger.info("Deleted %d events (before=%s)", deleted, before)
    return {"deleted": deleted}


@v1.get("/event-types")
async def list_event_types():
    """List all supported event types."""
    return EVENT_TYPES


app.include_router(v1)


# ── Backwards-compatible unversioned aliases ────────────────────
# These forward to the v1 endpoints so existing integrations keep working.

compat = APIRouter(tags=["compat"])


@compat.post("/events", status_code=201, response_model=EventResponse, include_in_schema=False)
@limiter.limit(config.RATE_LIMIT_PUBLISH)
async def compat_publish_event(request: Request, event: Event, _=Depends(require_auth)):
    return await publish_event(request, event, _)


@compat.get("/events", response_model=List[EventResponse], include_in_schema=False)
@limiter.limit(config.RATE_LIMIT_QUERY)
async def compat_get_events(
    request: Request,
    event_type: Optional[str] = Query(None, max_length=50),
    session_id: Optional[str] = Query(None, max_length=200),
    user_id: Optional[str] = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=1000),
    since: Optional[str] = Query(None, max_length=30),
    _=Depends(require_auth),
):
    return await get_events(request, event_type, session_id, user_id, limit, since, _)


@compat.get("/events/{event_id}", response_model=EventResponse, include_in_schema=False)
@limiter.limit(config.RATE_LIMIT_QUERY)
async def compat_get_event(request: Request, event_id: str, _=Depends(require_auth)):
    return await get_event(request, event_id, _)


@compat.get("/stats", include_in_schema=False)
@limiter.limit(config.RATE_LIMIT_QUERY)
async def compat_get_stats(request: Request, _=Depends(require_auth)):
    return await get_stats(request, _)


@compat.delete("/events", include_in_schema=False)
@limiter.limit(config.RATE_LIMIT_ADMIN)
async def compat_clear_events(
    request: Request,
    before: Optional[str] = Query(None),
    _=Depends(require_admin),
):
    return await clear_events(request, before, _)


@compat.get("/event-types", include_in_schema=False)
async def compat_list_event_types():
    return await list_event_types()


app.include_router(compat)


# ── WebSocket Endpoints ─────────────────────────────────────────


@app.websocket("/ws/publish")
async def websocket_publish(websocket: WebSocket):
    """WebSocket endpoint for high-frequency event publishing."""
    try:
        verify_ws_api_key(websocket)
    except HTTPException:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    client_ip = websocket.client.host if websocket.client else "unknown"
    if not ws_limiter.try_connect(client_ip):
        await websocket.close(code=4002, reason="Too many connections")
        return

    await websocket.accept()

    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > config.MAX_WS_MESSAGE_BYTES:
                await websocket.send_json({"status": "error", "message": "Message too large"})
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"status": "error", "message": "Invalid JSON"})
                continue

            try:
                event = Event(**data)
                event_id = f"evt_{uuid.uuid4().hex[:12]}"
                timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

                insert_event(
                    event_id=event_id,
                    event_type=event.event_type,
                    source=event.source,
                    session_id=event.session_id,
                    user_id=event.user_id,
                    payload=event.payload,
                    timestamp=timestamp,
                )

                event_response = EventResponse(
                    id=event_id,
                    event_type=event.event_type,
                    source=event.source,
                    session_id=event.session_id,
                    user_id=event.user_id,
                    payload=event.payload,
                    timestamp=timestamp,
                )
                await event_router.publish(event_response)

                await websocket.send_json({"status": "ok", "event_id": event_id})
            except ValueError as e:
                await websocket.send_json({"status": "error", "message": str(e)})
            except Exception:
                logger.exception("WebSocket publish error")
                await websocket.send_json({"status": "error", "message": "Internal error"})

    except WebSocketDisconnect:
        pass
    finally:
        ws_limiter.disconnect(client_ip)


@app.websocket("/ws/subscribe")
async def websocket_subscribe(websocket: WebSocket):
    """WebSocket endpoint for subscribing to real-time events."""
    try:
        verify_ws_api_key(websocket)
    except HTTPException:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    client_ip = websocket.client.host if websocket.client else "unknown"
    if not ws_limiter.try_connect(client_ip):
        await websocket.close(code=4002, reason="Too many connections")
        return

    subscriber_id = f"sub_{uuid.uuid4().hex[:8]}"
    await websocket.accept()

    try:
        # First message: subscription config
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        if len(raw) > config.MAX_WS_MESSAGE_BYTES:
            await websocket.send_json({"status": "error", "message": "Message too large"})
            return

        try:
            ws_config = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_json({"status": "error", "message": "Invalid JSON"})
            return

        filters = {}
        if "event_types" in ws_config:
            filters["event_types"] = ws_config["event_types"]
        if "session_id" in ws_config:
            filters["session_id"] = ws_config["session_id"]
        if "user_id" in ws_config:
            filters["user_id"] = ws_config["user_id"]

        if not await event_router.subscribe(subscriber_id, websocket, filters):
            await websocket.send_json(
                {"status": "error", "message": "Server at subscriber capacity"}
            )
            return

        await websocket.send_json({
            "status": "subscribed",
            "subscriber_id": subscriber_id,
            "filters": filters,
        })

        # Keep-alive loop
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if len(raw) > config.MAX_WS_MESSAGE_BYTES:
                    await websocket.send_json(
                        {"status": "error", "message": "Message too large"}
                    )
                    continue

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg.get("type") == "update_filters":
                    new_filters = msg.get("filters", {})
                    event_router.filters[subscriber_id] = new_filters
                    await websocket.send_json({
                        "status": "filters_updated",
                        "filters": new_filters,
                    })
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "keepalive"})

    except WebSocketDisconnect:
        event_router.unsubscribe(subscriber_id)
    except asyncio.TimeoutError:
        logger.info("Subscriber %s timed out waiting for config", subscriber_id)
        event_router.unsubscribe(subscriber_id)
    except Exception:
        logger.exception("Subscriber error for %s", subscriber_id)
        event_router.unsubscribe(subscriber_id)
    finally:
        ws_limiter.disconnect(client_ip)


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
