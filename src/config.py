"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

# Server
HOST = os.getenv("HOST", "0.0.0.0")  # nosec B104 — intentional for containerized deployment
PORT = int(os.getenv("PORT", "8001"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Database
DATABASE_PATH = Path(
    os.getenv("DATABASE_PATH", str(Path(__file__).parent.parent / "data" / "events.db"))
)

# CORS
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]

# Authentication
API_KEY = os.getenv("API_KEY", "")
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "false").lower() == "true"

# Rate limiting
RATE_LIMIT_PUBLISH = os.getenv("RATE_LIMIT_PUBLISH", "200/minute")
RATE_LIMIT_QUERY = os.getenv("RATE_LIMIT_QUERY", "600/minute")
RATE_LIMIT_ADMIN = os.getenv("RATE_LIMIT_ADMIN", "10/minute")

# Router limits
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "10000"))
MAX_SUBSCRIBERS = int(os.getenv("MAX_SUBSCRIBERS", "5000"))

# WebSocket limits
MAX_WS_MESSAGE_BYTES = int(os.getenv("MAX_WS_MESSAGE_BYTES", str(1024 * 1024)))  # 1 MB
MAX_WS_CONNECTIONS_PER_IP = int(os.getenv("MAX_WS_CONNECTIONS_PER_IP", "20"))

# Payload limits
MAX_PAYLOAD_KEYS = int(os.getenv("MAX_PAYLOAD_KEYS", "50"))
MAX_PAYLOAD_BYTES = int(os.getenv("MAX_PAYLOAD_BYTES", str(64 * 1024)))  # 64 KB

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "text")  # "text" or "json"

# Version
VERSION = "2.0.0"
