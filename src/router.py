"""Event pub/sub router with bounded queue and subscriber limits."""

import asyncio
import logging
from typing import Dict, Optional

from fastapi import WebSocket

from src.config import MAX_QUEUE_SIZE, MAX_SUBSCRIBERS
from src.models import EventResponse

logger = logging.getLogger(__name__)


class EventRouter:
    """Routes events from publishers to matching WebSocket subscribers."""

    def __init__(
        self,
        max_queue_size: int = MAX_QUEUE_SIZE,
        max_subscribers: int = MAX_SUBSCRIBERS,
    ):
        self.subscribers: Dict[str, WebSocket] = {}
        self.filters: Dict[str, dict] = {}
        self.max_subscribers = max_subscribers
        self.event_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._processor_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Start the background event processor."""
        self._processor_task = asyncio.create_task(self._process_events())
        logger.info("Event router started")

    def stop(self) -> None:
        """Stop the background event processor."""
        if self._processor_task:
            self._processor_task.cancel()
            logger.info("Event router stopped")

    async def subscribe(
        self, subscriber_id: str, websocket: WebSocket, filters: dict
    ) -> bool:
        """Add a subscriber. Returns False if at capacity."""
        if len(self.subscribers) >= self.max_subscribers:
            logger.warning(
                "Subscriber rejected (at capacity): %s", subscriber_id
            )
            return False
        self.subscribers[subscriber_id] = websocket
        self.filters[subscriber_id] = filters
        logger.info("Subscriber added: %s filters=%s", subscriber_id, filters)
        return True

    def unsubscribe(self, subscriber_id: str) -> None:
        """Remove a subscriber."""
        if subscriber_id in self.subscribers:
            del self.subscribers[subscriber_id]
            del self.filters[subscriber_id]
            logger.info("Subscriber removed: %s", subscriber_id)

    async def publish(self, event: EventResponse) -> bool:
        """Publish an event to the queue. Returns False if queue is full."""
        try:
            self.event_queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            logger.error("Event queue full, dropping event %s", event.id)
            return False

    async def _process_events(self) -> None:
        """Process events from the queue and route to subscribers."""
        while True:
            try:
                event = await self.event_queue.get()
                await self._route_event(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error processing event: %s", e)

    async def _route_event(self, event: EventResponse) -> None:
        """Route an event to matching subscribers."""
        disconnected = []

        for subscriber_id, websocket in self.subscribers.items():
            if self._matches_filter(event, self.filters[subscriber_id]):
                try:
                    await websocket.send_json(event.model_dump())
                except Exception:
                    disconnected.append(subscriber_id)

        for sub_id in disconnected:
            self.unsubscribe(sub_id)

    def _matches_filter(self, event: EventResponse, filters: dict) -> bool:
        """Check if event matches subscriber's filters."""
        if not filters:
            return True

        if "event_types" in filters and filters["event_types"]:
            if event.event_type not in filters["event_types"]:
                return False

        if "session_id" in filters and filters["session_id"]:
            if event.session_id != filters["session_id"]:
                return False

        if "user_id" in filters and filters["user_id"]:
            if event.user_id != filters["user_id"]:
                return False

        return True

    def get_stats(self) -> dict:
        """Get router statistics."""
        return {
            "active_subscribers": len(self.subscribers),
            "queue_size": self.event_queue.qsize(),
        }
