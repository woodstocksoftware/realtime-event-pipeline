"""Tests for the Real-Time Event Pipeline."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# Ensure auth is disabled for most tests
os.environ["REQUIRE_AUTH"] = "false"

from src.config import DATABASE_PATH
from src.models import EventResponse
from src.router import EventRouter
from src.server import app


@pytest.fixture(autouse=True)
def clean_database():
    """Reset database before each test."""
    import sqlite3

    conn = sqlite3.connect(str(DATABASE_PATH))
    cursor = conn.cursor()
    cursor.execute("DELETE FROM events")
    cursor.execute("DELETE FROM event_stats")
    conn.commit()
    conn.close()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_event():
    return {
        "event_type": "quiz_started",
        "source": "quiz_engine",
        "session_id": "session-123",
        "user_id": "student-456",
        "payload": {"quiz_id": "math-101"},
    }


# ── Health & Readiness ──────────────────────────────────────────


class TestHealth:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "event-pipeline"
        assert "version" in data

    def test_readiness_check(self, client):
        response = client.get("/readiness")
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert data["database"] == "connected"
        assert "router" in data


# ── Publish Events (versioned) ──────────────────────────────────


class TestPublishEvent:
    def test_publish_returns_201(self, client, sample_event):
        response = client.post("/api/v1/events", json=sample_event)
        assert response.status_code == 201
        data = response.json()
        assert data["id"].startswith("evt_")
        assert data["event_type"] == "quiz_started"
        assert data["source"] == "quiz_engine"
        assert data["session_id"] == "session-123"
        assert data["user_id"] == "student-456"
        assert data["payload"] == {"quiz_id": "math-101"}
        assert "timestamp" in data

    def test_publish_minimal_event(self, client):
        response = client.post("/api/v1/events", json={
            "event_type": "session_created",
            "source": "system",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["session_id"] is None
        assert data["user_id"] is None
        assert data["payload"] == {}

    def test_publish_missing_required_fields(self, client):
        response = client.post("/api/v1/events", json={"event_type": "quiz_started"})
        assert response.status_code == 422

    def test_publish_empty_body(self, client):
        response = client.post("/api/v1/events", json={})
        assert response.status_code == 422

    def test_compat_unversioned_publish(self, client, sample_event):
        """Backwards-compatible unversioned endpoint still works."""
        response = client.post("/events", json=sample_event)
        assert response.status_code == 201


# ── Input Validation ────────────────────────────────────────────


class TestInputValidation:
    def test_invalid_event_type_rejected(self, client):
        response = client.post("/api/v1/events", json={
            "event_type": "not_a_real_type",
            "source": "quiz_engine",
        })
        assert response.status_code == 422
        assert "not_a_real_type" in response.text

    def test_source_too_long(self, client):
        response = client.post("/api/v1/events", json={
            "event_type": "quiz_started",
            "source": "x" * 101,
        })
        assert response.status_code == 422

    def test_source_invalid_characters(self, client):
        response = client.post("/api/v1/events", json={
            "event_type": "quiz_started",
            "source": "bad source!@#",
        })
        assert response.status_code == 422

    def test_payload_too_many_keys(self, client):
        response = client.post("/api/v1/events", json={
            "event_type": "quiz_started",
            "source": "quiz_engine",
            "payload": {f"key_{i}": i for i in range(51)},
        })
        assert response.status_code == 422

    def test_invalid_since_timestamp(self, client):
        response = client.get("/api/v1/events?since=not-a-date")
        assert response.status_code == 400
        assert "timestamp" in response.json()["detail"].lower()

    def test_payload_too_large_bytes(self, client):
        response = client.post("/api/v1/events", json={
            "event_type": "quiz_started",
            "source": "quiz_engine",
            "payload": {"data": "x" * 70000},
        })
        assert response.status_code == 422


# ── Query Events ────────────────────────────────────────────────


class TestQueryEvents:
    def test_get_events_empty(self, client):
        response = client.get("/api/v1/events")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_events_after_publish(self, client, sample_event):
        client.post("/api/v1/events", json=sample_event)
        response = client.get("/api/v1/events")
        assert response.status_code == 200
        events = response.json()
        assert len(events) == 1
        assert events[0]["event_type"] == "quiz_started"

    def test_filter_by_event_type(self, client, sample_event):
        client.post("/api/v1/events", json=sample_event)
        client.post("/api/v1/events", json={
            "event_type": "answer_submitted",
            "source": "quiz_engine",
        })
        response = client.get("/api/v1/events?event_type=quiz_started")
        events = response.json()
        assert len(events) == 1
        assert events[0]["event_type"] == "quiz_started"

    def test_filter_by_session_id(self, client, sample_event):
        client.post("/api/v1/events", json=sample_event)
        client.post("/api/v1/events", json={
            "event_type": "quiz_started",
            "source": "quiz_engine",
            "session_id": "other-session",
        })
        response = client.get("/api/v1/events?session_id=session-123")
        events = response.json()
        assert len(events) == 1
        assert events[0]["session_id"] == "session-123"

    def test_filter_by_user_id(self, client, sample_event):
        client.post("/api/v1/events", json=sample_event)
        response = client.get("/api/v1/events?user_id=student-456")
        events = response.json()
        assert len(events) == 1
        assert events[0]["user_id"] == "student-456"

    def test_limit_parameter(self, client, sample_event):
        for _ in range(5):
            client.post("/api/v1/events", json=sample_event)
        response = client.get("/api/v1/events?limit=3")
        assert len(response.json()) == 3

    def test_events_ordered_by_timestamp_desc(self, client):
        client.post("/api/v1/events", json={
            "event_type": "quiz_started",
            "source": "quiz_engine",
        })
        client.post("/api/v1/events", json={
            "event_type": "answer_submitted",
            "source": "quiz_engine",
        })
        events = client.get("/api/v1/events").json()
        assert events[0]["event_type"] == "answer_submitted"
        assert events[1]["event_type"] == "quiz_started"

    def test_filter_by_since_returns_recent(self, client, sample_event):
        client.post("/api/v1/events", json=sample_event)
        response = client.get("/api/v1/events?since=2000-01-01T00:00:00Z")
        assert len(response.json()) == 1

    def test_filter_by_since_excludes_old(self, client, sample_event):
        client.post("/api/v1/events", json=sample_event)
        response = client.get("/api/v1/events?since=2099-01-01T00:00:00Z")
        assert response.json() == []


# ── Get Single Event ────────────────────────────────────────────


class TestGetEvent:
    def test_get_event_by_id(self, client, sample_event):
        published = client.post("/api/v1/events", json=sample_event).json()
        response = client.get(f"/api/v1/events/{published['id']}")
        assert response.status_code == 200
        assert response.json()["id"] == published["id"]

    def test_get_nonexistent_event(self, client):
        response = client.get("/api/v1/events/evt_doesnotexist")
        assert response.status_code == 404


# ── Statistics ──────────────────────────────────────────────────


class TestStats:
    def test_stats_empty(self, client):
        response = client.get("/api/v1/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_events"] == 0
        assert data["by_type"] == []

    def test_stats_after_publish(self, client, sample_event):
        client.post("/api/v1/events", json=sample_event)
        client.post("/api/v1/events", json=sample_event)
        data = client.get("/api/v1/stats").json()
        assert data["total_events"] == 2
        assert len(data["by_type"]) == 1
        assert data["by_type"][0]["event_type"] == "quiz_started"
        assert data["by_type"][0]["count"] == 2

    def test_stats_includes_router_info(self, client):
        data = client.get("/api/v1/stats").json()
        assert "router" in data
        assert "active_subscribers" in data["router"]
        assert "queue_size" in data["router"]


# ── Event Types ─────────────────────────────────────────────────


class TestEventTypes:
    def test_list_event_types(self, client):
        response = client.get("/api/v1/event-types")
        assert response.status_code == 200
        data = response.json()
        assert "quiz_started" in data
        assert "answer_submitted" in data
        assert "mastery_updated" in data
        assert len(data) == 15


# ── Delete Events ───────────────────────────────────────────────


class TestDeleteEvents:
    def test_delete_all_events(self, client, sample_event):
        client.post("/api/v1/events", json=sample_event)
        client.post("/api/v1/events", json=sample_event)
        response = client.delete("/api/v1/events")
        assert response.status_code == 200
        assert response.json()["deleted"] >= 2
        assert client.get("/api/v1/events").json() == []

    def test_delete_with_before_filter(self, client, sample_event):
        client.post("/api/v1/events", json=sample_event)
        response = client.delete("/api/v1/events?before=2099-01-01T00:00:00Z")
        assert response.status_code == 200
        assert response.json()["deleted"] >= 1

    def test_delete_rejects_invalid_before(self, client):
        response = client.delete("/api/v1/events?before=not-a-date")
        assert response.status_code == 400


# ── Security Headers ────────────────────────────────────────────


class TestSecurityHeaders:
    def test_security_headers_present(self, client):
        response = client.get("/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "default-src" in response.headers["Content-Security-Policy"]


# ── Authentication ──────────────────────────────────────────────


class TestAuthentication:
    def test_auth_not_required_when_disabled(self, client, sample_event):
        """With REQUIRE_AUTH=false, endpoints work without API key."""
        response = client.post("/api/v1/events", json=sample_event)
        assert response.status_code == 201

    def test_auth_required_when_enabled(self, client, sample_event, monkeypatch):
        """With REQUIRE_AUTH=true, endpoints reject requests without API key."""
        monkeypatch.setattr("src.middleware.REQUIRE_AUTH", True)
        monkeypatch.setattr("src.middleware.API_KEY", "test-key-123")

        # No key → 401
        response = client.post("/api/v1/events", json=sample_event)
        assert response.status_code == 401

        # Wrong key → 401
        response = client.post(
            "/api/v1/events",
            json=sample_event,
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

        # Correct key → 201
        response = client.post(
            "/api/v1/events",
            json=sample_event,
            headers={"X-API-Key": "test-key-123"},
        )
        assert response.status_code == 201

    def test_admin_auth_on_delete(self, client, sample_event, monkeypatch):
        """DELETE /events requires admin auth when enabled."""
        monkeypatch.setattr("src.middleware.REQUIRE_AUTH", True)
        monkeypatch.setattr("src.middleware.API_KEY", "admin-key")

        response = client.delete("/api/v1/events")
        assert response.status_code == 401

        response = client.delete(
            "/api/v1/events",
            headers={"X-API-Key": "admin-key"},
        )
        assert response.status_code == 200


# ── EventRouter Unit Tests ──────────────────────────────────────


class TestEventRouter:
    def test_initial_state(self):
        r = EventRouter(max_queue_size=100, max_subscribers=10)
        assert r.subscribers == {}
        assert r.filters == {}
        stats = r.get_stats()
        assert stats["active_subscribers"] == 0
        assert stats["queue_size"] == 0

    def test_unsubscribe(self):
        r = EventRouter(max_queue_size=100, max_subscribers=10)
        r.subscribers["sub-1"] = "mock"
        r.filters["sub-1"] = {}
        r.unsubscribe("sub-1")
        assert "sub-1" not in r.subscribers
        assert "sub-1" not in r.filters

    def test_unsubscribe_nonexistent(self):
        r = EventRouter(max_queue_size=100, max_subscribers=10)
        r.unsubscribe("nonexistent")  # should not raise

    def test_matches_filter_no_filters(self):
        r = EventRouter(max_queue_size=100, max_subscribers=10)
        event = EventResponse(
            id="evt_1", event_type="quiz_started", source="test",
            session_id=None, user_id=None, payload={}, timestamp="2026-01-01T00:00:00Z",
        )
        assert r._matches_filter(event, {}) is True
        assert r._matches_filter(event, None) is True

    def test_matches_filter_by_event_type(self):
        r = EventRouter(max_queue_size=100, max_subscribers=10)
        event = EventResponse(
            id="evt_1", event_type="quiz_started", source="test",
            session_id=None, user_id=None, payload={}, timestamp="2026-01-01T00:00:00Z",
        )
        assert r._matches_filter(event, {"event_types": ["quiz_started"]}) is True
        assert r._matches_filter(event, {"event_types": ["answer_submitted"]}) is False

    def test_matches_filter_by_session(self):
        r = EventRouter(max_queue_size=100, max_subscribers=10)
        event = EventResponse(
            id="evt_1", event_type="quiz_started", source="test",
            session_id="s-1", user_id=None, payload={}, timestamp="2026-01-01T00:00:00Z",
        )
        assert r._matches_filter(event, {"session_id": "s-1"}) is True
        assert r._matches_filter(event, {"session_id": "s-2"}) is False

    def test_matches_filter_by_user(self):
        r = EventRouter(max_queue_size=100, max_subscribers=10)
        event = EventResponse(
            id="evt_1", event_type="quiz_started", source="test",
            session_id=None, user_id="u-1", payload={}, timestamp="2026-01-01T00:00:00Z",
        )
        assert r._matches_filter(event, {"user_id": "u-1"}) is True
        assert r._matches_filter(event, {"user_id": "u-2"}) is False

    def test_matches_filter_combined(self):
        r = EventRouter(max_queue_size=100, max_subscribers=10)
        event = EventResponse(
            id="evt_1", event_type="quiz_started", source="test",
            session_id="s-1", user_id="u-1", payload={}, timestamp="2026-01-01T00:00:00Z",
        )
        assert r._matches_filter(event, {
            "event_types": ["quiz_started"],
            "session_id": "s-1",
            "user_id": "u-1",
        }) is True
        assert r._matches_filter(event, {
            "event_types": ["quiz_started"],
            "session_id": "s-1",
            "user_id": "u-2",
        }) is False


# ── WebSocket Publish ───────────────────────────────────────────


class TestWebSocketPublish:
    def test_publish_via_websocket(self, client, sample_event):
        with client.websocket_connect("/ws/publish") as ws:
            ws.send_json(sample_event)
            response = ws.receive_json()
            assert response["status"] == "ok"
            assert response["event_id"].startswith("evt_")

    def test_publish_invalid_event_via_websocket(self, client):
        with client.websocket_connect("/ws/publish") as ws:
            ws.send_json({"event_type": "not_valid", "source": "x"})
            response = ws.receive_json()
            assert response["status"] == "error"


# ── WebSocket Subscribe ─────────────────────────────────────────


class TestWebSocketSubscribe:
    def test_subscribe_receives_confirmation(self, client):
        with client.websocket_connect("/ws/subscribe") as ws:
            ws.send_json({"event_types": ["quiz_started"]})
            response = ws.receive_json()
            assert response["status"] == "subscribed"
            assert "subscriber_id" in response
            assert response["filters"]["event_types"] == ["quiz_started"]

    def test_subscribe_with_session_filter(self, client):
        with client.websocket_connect("/ws/subscribe") as ws:
            ws.send_json({
                "event_types": ["quiz_started"],
                "session_id": "session-123",
            })
            response = ws.receive_json()
            assert response["status"] == "subscribed"
            assert response["filters"]["session_id"] == "session-123"

    def test_subscribe_ping_pong(self, client):
        with client.websocket_connect("/ws/subscribe") as ws:
            ws.send_json({"event_types": ["quiz_started"]})
            ws.receive_json()  # subscription confirmation
            ws.send_json({"type": "ping"})
            response = ws.receive_json()
            assert response["type"] == "pong"


# ── Readiness Failure ──────────────────────────────────────────


class TestReadinessFailure:
    def test_readiness_returns_503_on_db_failure(self, client, monkeypatch):
        def broken_connection():
            raise Exception("DB connection failed")

        monkeypatch.setattr("src.database.get_connection", broken_connection)
        response = client.get("/readiness")
        assert response.status_code == 503
        assert response.json()["ready"] is False


# ── HSTS Header ────────────────────────────────────────────────


class TestHSTSHeader:
    def test_hsts_header_present_on_https(self):
        with TestClient(app, base_url="https://testserver") as c:
            response = c.get("/health")
            assert "Strict-Transport-Security" in response.headers

    def test_hsts_header_absent_on_http(self, client):
        response = client.get("/health")
        assert "Strict-Transport-Security" not in response.headers


# ── WebSocket Publish Error Paths ──────────────────────────────


class TestWebSocketPublishErrorPaths:
    def test_publish_invalid_json(self, client):
        with client.websocket_connect("/ws/publish") as ws:
            ws.send_text("{not valid json")
            response = ws.receive_json()
            assert response["status"] == "error"
            assert "Invalid JSON" in response["message"]

    def test_publish_oversized_message(self, client, monkeypatch):
        monkeypatch.setattr("src.config.MAX_WS_MESSAGE_BYTES", 50)
        with client.websocket_connect("/ws/publish") as ws:
            ws.send_text("x" * 200)
            response = ws.receive_json()
            assert response["status"] == "error"
            assert "too large" in response["message"].lower()

    def test_publish_internal_error(self, client, monkeypatch):
        """Non-ValueError exceptions return generic 'Internal error'."""
        def raise_runtime(**kwargs):
            raise RuntimeError("DB crash")

        monkeypatch.setattr("src.server.insert_event", raise_runtime)
        with client.websocket_connect("/ws/publish") as ws:
            ws.send_json({
                "event_type": "quiz_started",
                "source": "quiz_engine",
            })
            response = ws.receive_json()
            assert response["status"] == "error"
            assert response["message"] == "Internal error"


# ── WebSocket Subscribe Error Paths ────────────────────────────


class TestWebSocketSubscribeErrorPaths:
    def test_subscribe_rejects_oversized_config(self, client, monkeypatch):
        monkeypatch.setattr("src.config.MAX_WS_MESSAGE_BYTES", 10)
        with client.websocket_connect("/ws/subscribe") as ws:
            ws.send_text("x" * 200)
            response = ws.receive_json()
            assert response["status"] == "error"
            assert "too large" in response["message"].lower()

    def test_subscribe_rejects_invalid_json_config(self, client):
        with client.websocket_connect("/ws/subscribe") as ws:
            ws.send_text("{not valid json")
            response = ws.receive_json()
            assert response["status"] == "error"
            assert "Invalid JSON" in response["message"]

    def test_subscribe_at_server_capacity(self, client, monkeypatch):
        from src.server import event_router

        monkeypatch.setattr(event_router, "max_subscribers", 0)
        with client.websocket_connect("/ws/subscribe") as ws:
            ws.send_json({"event_types": ["quiz_started"]})
            response = ws.receive_json()
            assert response["status"] == "error"
            assert "capacity" in response["message"].lower()

    def test_update_filters(self, client):
        with client.websocket_connect("/ws/subscribe") as ws:
            ws.send_json({"event_types": ["quiz_started"]})
            confirm = ws.receive_json()
            assert confirm["status"] == "subscribed"

            ws.send_json({
                "type": "update_filters",
                "filters": {"session_id": "new-session-789"},
            })
            response = ws.receive_json()
            assert response["status"] == "filters_updated"
            assert response["filters"]["session_id"] == "new-session-789"

    def test_subscribe_oversized_message_in_loop(self, client, monkeypatch):
        with client.websocket_connect("/ws/subscribe") as ws:
            ws.send_json({"event_types": ["quiz_started"]})
            ws.receive_json()  # confirmation

            monkeypatch.setattr("src.config.MAX_WS_MESSAGE_BYTES", 10)
            ws.send_text("x" * 200)
            response = ws.receive_json()
            assert response["status"] == "error"
            assert "too large" in response["message"].lower()

    def test_subscribe_invalid_json_in_loop(self, client):
        with client.websocket_connect("/ws/subscribe") as ws:
            ws.send_json({"event_types": ["quiz_started"]})
            ws.receive_json()  # confirmation

            ws.send_text("{not valid json")
            # Server does `continue` on invalid JSON, so send a ping to verify alive
            ws.send_json({"type": "ping"})
            response = ws.receive_json()
            assert response["type"] == "pong"


# ── WebSocket Auth (direct middleware tests) ───────────────────


class TestVerifyWsApiKey:
    def test_rejects_missing_key(self, monkeypatch):
        from src.middleware import verify_ws_api_key

        monkeypatch.setattr("src.middleware.REQUIRE_AUTH", True)
        monkeypatch.setattr("src.middleware.API_KEY", "secret-key")

        mock_ws = MagicMock()
        mock_ws.query_params = {}
        mock_ws.headers = {}

        with pytest.raises(HTTPException) as exc_info:
            verify_ws_api_key(mock_ws)
        assert exc_info.value.status_code == 401

    def test_rejects_wrong_key(self, monkeypatch):
        from src.middleware import verify_ws_api_key

        monkeypatch.setattr("src.middleware.REQUIRE_AUTH", True)
        monkeypatch.setattr("src.middleware.API_KEY", "secret-key")

        mock_ws = MagicMock()
        mock_ws.query_params = {"api_key": "wrong-key"}
        mock_ws.headers = {}

        with pytest.raises(HTTPException):
            verify_ws_api_key(mock_ws)

    def test_accepts_query_param_key(self, monkeypatch):
        from src.middleware import verify_ws_api_key

        monkeypatch.setattr("src.middleware.REQUIRE_AUTH", True)
        monkeypatch.setattr("src.middleware.API_KEY", "secret-key")

        mock_ws = MagicMock()
        mock_ws.query_params = {"api_key": "secret-key"}
        mock_ws.headers = {}

        verify_ws_api_key(mock_ws)  # should not raise

    def test_accepts_header_key(self, monkeypatch):
        from src.middleware import verify_ws_api_key

        monkeypatch.setattr("src.middleware.REQUIRE_AUTH", True)
        monkeypatch.setattr("src.middleware.API_KEY", "secret-key")

        mock_ws = MagicMock()
        mock_ws.query_params = {}
        mock_ws.headers = {"x-api-key": "secret-key"}

        verify_ws_api_key(mock_ws)  # should not raise


# ── WebSocket Connection Limiter ───────────────────────────────


class TestWebSocketConnectionLimiterUnit:
    def test_try_connect_at_limit(self):
        from src.middleware import WebSocketConnectionLimiter

        limiter = WebSocketConnectionLimiter(max_per_ip=2)
        assert limiter.try_connect("1.2.3.4") is True
        assert limiter.try_connect("1.2.3.4") is True
        assert limiter.try_connect("1.2.3.4") is False

    def test_disconnect_frees_slot(self):
        from src.middleware import WebSocketConnectionLimiter

        limiter = WebSocketConnectionLimiter(max_per_ip=1)
        assert limiter.try_connect("1.2.3.4") is True
        assert limiter.try_connect("1.2.3.4") is False
        limiter.disconnect("1.2.3.4")
        assert limiter.try_connect("1.2.3.4") is True

    def test_disconnect_cleans_up_zero_connections(self):
        from src.middleware import WebSocketConnectionLimiter

        limiter = WebSocketConnectionLimiter(max_per_ip=5)
        limiter.try_connect("1.2.3.4")
        limiter.disconnect("1.2.3.4")
        assert "1.2.3.4" not in limiter._connections

    def test_different_ips_independent(self):
        from src.middleware import WebSocketConnectionLimiter

        limiter = WebSocketConnectionLimiter(max_per_ip=1)
        assert limiter.try_connect("1.1.1.1") is True
        assert limiter.try_connect("2.2.2.2") is True
        assert limiter.try_connect("1.1.1.1") is False


# ── EventRouter Async Tests ───────────────────────────────────


class TestEventRouterAsync:
    def test_start_creates_processor_task(self):
        async def _test():
            r = EventRouter(max_queue_size=100, max_subscribers=10)
            r.start()
            assert r._processor_task is not None
            assert not r._processor_task.done()
            r.stop()
            await asyncio.sleep(0.05)

        asyncio.run(_test())

    def test_stop_cancels_task(self):
        async def _test():
            r = EventRouter(max_queue_size=100, max_subscribers=10)
            r.start()
            task = r._processor_task
            r.stop()
            await asyncio.sleep(0.05)
            assert task.cancelled()

        asyncio.run(_test())

    def test_stop_without_start(self):
        """Calling stop before start should not raise."""
        r = EventRouter(max_queue_size=100, max_subscribers=10)
        r.stop()  # no-op, should not raise

    def test_subscribe_at_capacity(self):
        async def _test():
            r = EventRouter(max_queue_size=100, max_subscribers=1)
            assert await r.subscribe("sub-1", MagicMock(), {}) is True
            assert await r.subscribe("sub-2", MagicMock(), {}) is False
            assert len(r.subscribers) == 1

        asyncio.run(_test())

    def test_publish_queue_full(self):
        async def _test():
            r = EventRouter(max_queue_size=1, max_subscribers=10)
            event = EventResponse(
                id="evt_1", event_type="quiz_started", source="test",
                session_id=None, user_id=None, payload={}, timestamp="2026-01-01T00:00:00Z",
            )
            assert await r.publish(event) is True
            assert await r.publish(event) is False

        asyncio.run(_test())

    def test_route_event_delivers_to_matching_subscriber(self):
        async def _test():
            r = EventRouter(max_queue_size=100, max_subscribers=10)
            mock_ws = AsyncMock()
            await r.subscribe("sub-1", mock_ws, {"event_types": ["quiz_started"]})

            event = EventResponse(
                id="evt_1", event_type="quiz_started", source="test",
                session_id=None, user_id=None, payload={}, timestamp="2026-01-01T00:00:00Z",
            )
            await r._route_event(event)
            mock_ws.send_json.assert_called_once()

        asyncio.run(_test())

    def test_route_event_skips_non_matching_subscriber(self):
        async def _test():
            r = EventRouter(max_queue_size=100, max_subscribers=10)
            mock_ws = AsyncMock()
            await r.subscribe("sub-1", mock_ws, {"event_types": ["answer_submitted"]})

            event = EventResponse(
                id="evt_1", event_type="quiz_started", source="test",
                session_id=None, user_id=None, payload={}, timestamp="2026-01-01T00:00:00Z",
            )
            await r._route_event(event)
            mock_ws.send_json.assert_not_called()

        asyncio.run(_test())

    def test_route_event_removes_disconnected_subscriber(self):
        async def _test():
            r = EventRouter(max_queue_size=100, max_subscribers=10)
            mock_ws = AsyncMock()
            mock_ws.send_json.side_effect = Exception("Connection closed")
            await r.subscribe("sub-1", mock_ws, {})

            event = EventResponse(
                id="evt_1", event_type="quiz_started", source="test",
                session_id=None, user_id=None, payload={}, timestamp="2026-01-01T00:00:00Z",
            )
            await r._route_event(event)
            assert "sub-1" not in r.subscribers
            assert "sub-1" not in r.filters

        asyncio.run(_test())

    def test_process_events_delivers_from_queue(self):
        async def _test():
            r = EventRouter(max_queue_size=100, max_subscribers=10)
            mock_ws = AsyncMock()
            await r.subscribe("sub-1", mock_ws, {})
            r.start()

            event = EventResponse(
                id="evt_1", event_type="quiz_started", source="test",
                session_id=None, user_id=None, payload={}, timestamp="2026-01-01T00:00:00Z",
            )
            await r.publish(event)
            await asyncio.sleep(0.1)

            mock_ws.send_json.assert_called_once()
            r.stop()

        asyncio.run(_test())


# ── Compat Endpoints ───────────────────────────────────────────


class TestCompatEndpoints:
    def test_compat_get_events(self, client, sample_event):
        client.post("/api/v1/events", json=sample_event)
        response = client.get("/events")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_compat_get_event_by_id(self, client, sample_event):
        published = client.post("/api/v1/events", json=sample_event).json()
        response = client.get(f"/events/{published['id']}")
        assert response.status_code == 200
        assert response.json()["id"] == published["id"]

    def test_compat_get_stats(self, client):
        response = client.get("/stats")
        assert response.status_code == 200
        assert "total_events" in response.json()

    def test_compat_delete_events(self, client, sample_event):
        client.post("/api/v1/events", json=sample_event)
        response = client.delete("/events")
        assert response.status_code == 200
        assert response.json()["deleted"] >= 1

    def test_compat_list_event_types(self, client):
        response = client.get("/event-types")
        assert response.status_code == 200
        assert "quiz_started" in response.json()
