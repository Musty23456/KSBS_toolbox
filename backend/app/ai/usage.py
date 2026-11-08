"""Usage logging. Failures here must never break the user's request."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.ai_usage import AIUsageLog

logger = logging.getLogger("app.ai.usage")


def record_usage(
    db: Optional[Session],
    *,
    user_id: Optional[str],
    provider: str,
    model: str,
    request_type: str,
    success: bool,
    duration_ms: int,
    error_code: Optional[str] = None,
) -> None:
    if db is None:
        return
    try:
        db.add(
            AIUsageLog(
                user_id=user_id,
                provider=provider,
                model=model,
                request_type=request_type[:50],
                success=success,
                error_code=error_code,
                duration_ms=max(0, int(duration_ms)),
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("Could not record AI usage row", exc_info=False)
