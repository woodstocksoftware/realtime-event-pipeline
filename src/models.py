"""Pydantic models with input validation."""

import json
import sys
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

# ── Event Type Registry ─────────────────────────────────────────

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
    "error_occurred": "Error in system",
}


# ── Input / Output Models ───────────────────────────────────────


class Event(BaseModel):
    event_type: str = Field(
        ..., description="Type of event (e.g., quiz_started, answer_submitted)"
    )
    source: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_\-\.]+$",
        description="Source system identifier (e.g., quiz_engine)",
    )
    session_id: Optional[str] = Field(
        None, max_length=200, description="Quiz/test session ID"
    )
    user_id: Optional[str] = Field(
        None, max_length=200, description="User/student ID"
    )
    payload: dict = Field(
        default_factory=dict, description="Event-specific data"
    )

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError(
                f"Unknown event_type '{v}'. "
                f"Must be one of: {', '.join(sorted(EVENT_TYPES.keys()))}"
            )
        return v

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, v: dict) -> dict:
        from src.config import MAX_PAYLOAD_BYTES, MAX_PAYLOAD_KEYS

        if len(v) > MAX_PAYLOAD_KEYS:
            raise ValueError(
                f"Payload has {len(v)} keys (max {MAX_PAYLOAD_KEYS})"
            )
        size = sys.getsizeof(json.dumps(v))
        if size > MAX_PAYLOAD_BYTES:
            raise ValueError(
                f"Payload is {size} bytes (max {MAX_PAYLOAD_BYTES})"
            )
        return v


class EventResponse(BaseModel):
    id: str
    event_type: str
    source: str
    session_id: Optional[str]
    user_id: Optional[str]
    payload: dict
    timestamp: str


class SubscribeRequest(BaseModel):
    event_types: Optional[List[str]] = Field(
        None, description="Filter by event types"
    )
    session_id: Optional[str] = Field(None, description="Filter by session")
    user_id: Optional[str] = Field(None, description="Filter by user")
