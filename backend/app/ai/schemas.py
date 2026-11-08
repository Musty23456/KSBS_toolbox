"""Response models for the AI endpoints. None of them can carry a secret."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

ConnectionState = Literal["unknown", "connected", "failed"]


class AIStatusResponse(BaseModel):
    enabled: bool
    configured: bool  # a key is present (the key itself is never returned)
    provider: str
    model: str
    available: bool  # enabled and configured
    connection_status: ConnectionState
    last_checked_at: Optional[datetime] = None
    last_error_code: Optional[str] = None
    message: str


class AITestConnectionResponse(BaseModel):
    success: bool
    provider: str
    model: str
    latency_ms: int
    message: str
