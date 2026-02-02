"""
Real-Time Event Pipeline

Captures, routes, and processes events for the ed-tech platform.
"""

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime
from typing import Dict, Set, Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pathlib import Path


# ============================================================
# DATABASE
# ============================================================

DATABASE_PATH = Path(__file__).parent.parent / "data" / "events.db"


def get_connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.executescript("""
        -- Events table
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            session_id TEXT,
            user_id TEXT,
            payload TEXT,
            timestamp TEXT NOT NULL,
            processed INTEGER DEFAULT 0
        );
        
        -- Subscriptions (for reconnection)
        CREATE TABLE IF NOT EXISTS subscriptions (
            id TEXT PRIMARY KEY,
            subscriber_id TEXT NOT NULL,
            event_types TEXT,
            filters TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Event statistics
        CREATE TABLE IF NOT EXISTS event_stats (
            event_type TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0,
            last_seen TEXT
        );
        
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
    """)
    
    conn.commit()
    conn.close()


init_database()


# ============================================================
# EVENT MODELS
# ============================================================

class Event(BaseModel):
    event_type: str = Field(..., description="Type of event (e.g., quiz_started, answer_submitted)")
    source: str = Field(..., description="Source system (e.g., quiz_engine, timer_service)")
    session_id: Optional[str] = Field(None, description="Quiz/test session ID")
    user_id: Optional[str] = Field(None, description="User/student ID")
    payload: dict = Field(default_factory=dict, description="Event-specific data")


class EventResponse(BaseModel):
    id: str
    event_type: str
    source: str
    session_id: Optional[str]
    user_id: Optional[str]
    payload: dict
    timestamp: str


class SubscribeRequest(BaseModel):
    event_types: Optional[List[str]] = Field(None, description="Filter by event types")
    session_id: Optional[str] = Field(None, description="Filter by session")
    user_id: Optional[str] = Field(None, description="Filter by user")


# ============================================================
# EVENT ROUTER (PUB/SUB)
# ============================================================

class EventRouter:
    """Manages event routing and subscriptions."""
    
    def __init__(self):
        self.subscribers: Dict[str, WebSocket] = {}
        self.filters: Dict[str, dict] = {}
        self.event_queue: asyncio.Queue = asyncio.Queue()
        self._processor_task: Optional[asyncio.Task] = None
    
    def start(self):
        """Start the event processor."""
        self._processor_task = asyncio.create_task(self._process_events())
    
    def stop(self):
        """Stop the event processor."""
        if self._processor_task:
            self._processor_task.cancel()
    
    async def subscribe(self, subscriber_id: str, websocket: WebSocket, 
                        filters: dict = None):
        """Add a subscriber."""
        await websocket.accept()
        self.subscribers[subscriber_id] = websocket
        self.filters[subscriber_id] = filters or {}
        print(f"📥 Subscriber added: {subscriber_id} with filters: {filters}")
    
    def unsubscribe(self, subscriber_id: str):
        """Remove a subscriber."""
        if subscriber_id in self.subscribers:
            del self.subscribers[subscriber_id]
            del self.filters[subscriber_id]
            print(f"📤 Subscriber removed: {subscriber_id}")
    
    async def publish(self, event: EventResponse):
        """Publish an event to the queue."""
        await self.event_queue.put(event)
    
    async def _process_events(self):
        """Process events from the queue and route to subscribers."""
        while True:
            try:
                event = await self.event_queue.get()
                await self._route_event(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error processing event: {e}")
    
    async def _route_event(self, event: EventResponse):
        """Route an event to matching subscribers."""
        disconnected = []
        
        for subscriber_id, websocket in self.subscribers.items():
            if self._matches_filter(event, self.filters[subscriber_id]):
                try:
                    await websocket.send_json(event.model_dump())
                except Exception:
                    disconnected.append(subscriber_id)
        
        # Clean up disconnected subscribers
        for sub_id in disconnected:
            self.unsubscribe(sub_id)
    
    def _matches_filter(self, event: EventResponse, filters: dict) -> bool:
        """Check if event matches subscriber's filters."""
        if not filters:
            return True
        
        # Filter by event types
        if 'event_types' in filters and filters['event_types']:
            if event.event_type not in filters['event_types']:
                return False
        
        # Filter by session
        if 'session_id' in filters and filters['session_id']:
            if event.session_id != filters['session_id']:
                return False
        
        # Filter by user
        if 'user_id' in filters and filters['user_id']:
            if event.user_id != filters['user_id']:
                return False
        
        return True
    
    def get_stats(self) -> dict:
        """Get router statistics."""
        return {
            "active_subscribers": len(self.subscribers),
            "queue_size": self.event_queue.qsize()
        }


# Global router instance
router = EventRouter()


# ============================================================
# FASTAPI APP
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    router.start()
    print("🚀 Event Pipeline started!")
    yield
    router.stop()
    print("👋 Event Pipeline stopped!")


app = FastAPI(
    title="Real-Time Event Pipeline",
    description="Event ingestion, routing, and processing for ed-tech platform",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# REST ENDPOINTS
# ============================================================

@app.post("/events", response_model=EventResponse)
async def publish_event(event: Event):
    """
    Publish an event to the pipeline.
    
    Events are persisted and routed to all matching subscribers.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    timestamp = datetime.utcnow().isoformat() + "Z"
    
    # Persist event
    cursor.execute("""
        INSERT INTO events (id, event_type, source, session_id, user_id, payload, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, event.event_type, event.source, event.session_id,
          event.user_id, json.dumps(event.payload), timestamp))
    
    # Update stats
    cursor.execute("""
        INSERT INTO event_stats (event_type, count, last_seen)
        VALUES (?, 1, ?)
        ON CONFLICT(event_type) DO UPDATE SET
            count = count + 1,
            last_seen = excluded.last_seen
    """, (event.event_type, timestamp))
    
    conn.commit()
    conn.close()
    
    # Create response
    event_response = EventResponse(
        id=event_id,
        event_type=event.event_type,
        source=event.source,
        session_id=event.session_id,
        user_id=event.user_id,
        payload=event.payload,
        timestamp=timestamp
    )
    
    # Route to subscribers
    await router.publish(event_response)
    
    return event_response


@app.get("/events", response_model=List[EventResponse])
async def get_events(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    session_id: Optional[str] = Query(None, description="Filter by session"),
    user_id: Optional[str] = Query(None, description="Filter by user"),
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    since: Optional[str] = Query(None, description="Events after this timestamp (ISO format)")
):
    """
    Query persisted events with optional filters.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM events WHERE 1=1"
    params = []
    
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    
    if session_id:
        query += " AND session_id = ?"
        params.append(session_id)
    
    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)
    
    if since:
        query += " AND timestamp > ?"
        params.append(since)
    
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    events = []
    for row in rows:
        events.append(EventResponse(
            id=row['id'],
            event_type=row['event_type'],
            source=row['source'],
            session_id=row['session_id'],
            user_id=row['user_id'],
            payload=json.loads(row['payload']) if row['payload'] else {},
            timestamp=row['timestamp']
        ))
    
    return events


@app.get("/events/{event_id}", response_model=EventResponse)
async def get_event(event_id: str):
    """Get a specific event by ID."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    
    return EventResponse(
        id=row['id'],
        event_type=row['event_type'],
        source=row['source'],
        session_id=row['session_id'],
        user_id=row['user_id'],
        payload=json.loads(row['payload']) if row['payload'] else {},
        timestamp=row['timestamp']
    )


@app.get("/stats")
async def get_stats():
    """Get pipeline statistics."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Total events
    cursor.execute("SELECT COUNT(*) as total FROM events")
    total = cursor.fetchone()['total']
    
    # Events by type
    cursor.execute("SELECT event_type, count, last_seen FROM event_stats ORDER BY count DESC")
    by_type = [dict(row) for row in cursor.fetchall()]
    
    # Recent activity (last hour)
    cursor.execute("""
        SELECT COUNT(*) as count FROM events 
        WHERE timestamp > datetime('now', '-1 hour')
    """)
    last_hour = cursor.fetchone()['count']
    
    conn.close()
    
    return {
        "total_events": total,
        "events_last_hour": last_hour,
        "by_type": by_type,
        "router": router.get_stats()
    }


@app.delete("/events")
async def clear_events(before: Optional[str] = Query(None, description="Clear events before this timestamp")):
    """Clear old events (admin endpoint)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    if before:
        cursor.execute("DELETE FROM events WHERE timestamp < ?", (before,))
    else:
        cursor.execute("DELETE FROM events")
        cursor.execute("DELETE FROM event_stats")
    
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    return {"deleted": deleted}


# ============================================================
# WEBSOCKET ENDPOINTS
# ============================================================

@app.websocket("/ws/publish")
async def websocket_publish(websocket: WebSocket):
    """
    WebSocket endpoint for high-frequency event publishing.
    
    Send JSON events, receive confirmation.
    """
    await websocket.accept()
    
    try:
        while True:
            data = await websocket.receive_json()
            
            try:
                event = Event(**data)
                response = await publish_event(event)
                await websocket.send_json({
                    "status": "ok",
                    "event_id": response.id
                })
            except Exception as e:
                await websocket.send_json({
                    "status": "error",
                    "message": str(e)
                })
    
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/subscribe")
async def websocket_subscribe(websocket: WebSocket):
    """
    WebSocket endpoint for subscribing to events.
    
    Send a filter message first, then receive matching events.
    """
    subscriber_id = f"sub_{uuid.uuid4().hex[:8]}"
    
    try:
        # Wait for filter configuration
        await websocket.accept()
        
        # First message should be subscription config
        config = await websocket.receive_json()
        filters = {}
        
        if 'event_types' in config:
            filters['event_types'] = config['event_types']
        if 'session_id' in config:
            filters['session_id'] = config['session_id']
        if 'user_id' in config:
            filters['user_id'] = config['user_id']
        
        # Register with router (re-accept not needed, just update internal state)
        router.subscribers[subscriber_id] = websocket
        router.filters[subscriber_id] = filters
        print(f"📥 Subscriber added: {subscriber_id} with filters: {filters}")
        
        await websocket.send_json({
            "status": "subscribed",
            "subscriber_id": subscriber_id,
            "filters": filters
        })
        
        # Keep connection alive
        while True:
            # Handle ping/pong or filter updates
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=30)
                if msg.get('type') == 'ping':
                    await websocket.send_json({'type': 'pong'})
                elif msg.get('type') == 'update_filters':
                    router.filters[subscriber_id] = msg.get('filters', {})
                    await websocket.send_json({
                        "status": "filters_updated",
                        "filters": router.filters[subscriber_id]
                    })
            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_json({'type': 'keepalive'})
    
    except WebSocketDisconnect:
        router.unsubscribe(subscriber_id)
    except Exception as e:
        print(f"Subscriber error: {e}")
        router.unsubscribe(subscriber_id)


# ============================================================
# EVENT TYPE REGISTRY
# ============================================================

EVENT_TYPES = {
    # Quiz events
    "quiz_started": "Student started a quiz session",
    "quiz_completed": "Student completed/submitted quiz",
    "quiz_timeout": "Quiz timer expired",
    
    # Answer events
    "answer_submitted": "Student submitted an answer",
    "answer_changed": "Student changed their answer",
    
    # Navigation events
    "question_viewed": "Student viewed a question",
    "question_skipped": "Student skipped a question",
    
    # Timer events
    "timer_started": "Session timer started",
    "timer_tick": "Timer tick (usually every second)",
    "timer_warning": "Timer warning threshold reached",
    
    # Progress events
    "mastery_updated": "Student mastery level changed",
    "learning_gap_detected": "Learning gap identified",
    
    # System events
    "session_created": "New session created",
    "session_ended": "Session ended",
    "error_occurred": "Error in system"
}


@app.get("/event-types")
async def list_event_types():
    """List all supported event types."""
    return EVENT_TYPES


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
