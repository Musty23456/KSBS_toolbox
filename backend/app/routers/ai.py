from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai.config import get_ai_config
from app.ai.errors import AIRequestTooLargeError
from app.ai.rate_limit import ai_limiter
from app.ai.schemas import AIStatusResponse, AITestConnectionResponse
from app.ai.service import AIService
from app.database import get_db
from app.dependencies import require_roles
from app.models.user import RoleName, User

router = APIRouter(prefix="/api/ai", tags=["ai"])


async def enforce_request_size(request: Request) -> None:
    """Reject oversized bodies (declared or actual) before doing any work."""
    limit = get_ai_config().max_request_bytes
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise AIRequestTooLargeError()
        except ValueError:
            raise AIRequestTooLargeError() from None
    elif len(await request.body()) > limit:
        raise AIRequestTooLargeError()


def ai_access(bucket: str, *roles: RoleName):
    """
    Authenticate (existing JWT auth), authorise by role, check body size, then
    rate-limit per user. Order matters: anonymous callers get 401 and wrong
    roles 403 *before* they can consume rate-limit budget or reach any AI code.
    """

    def dependency(
        user: User = Depends(require_roles(*roles)),
        _size: None = Depends(enforce_request_size),
    ) -> User:
        ai_limiter.check(f"{bucket}:{user.id}", get_ai_config().rate_limit_per_minute)
        return user

    return dependency


def get_ai_service(db: Session = Depends(get_db)) -> AIService:
    return AIService(db=db)


@router.get("/status", response_model=AIStatusResponse)
def ai_status(
    current_user: User = Depends(ai_access("status", RoleName.ADMINISTRATOR, RoleName.SUPERVISOR)),
    service: AIService = Depends(get_ai_service),
):
    """AI availability, provider, model and the last known connection result.

    Never calls the provider (so it costs no quota) and never returns a secret.
    """
    return service.status()


@router.post("/test-connection", response_model=AITestConnectionResponse)
def ai_test_connection(
    current_user: User = Depends(ai_access("test", RoleName.ADMINISTRATOR)),
    service: AIService = Depends(get_ai_service),
):
    """Make one tiny provider call to verify the key, model and network path."""
    return service.test_connection(current_user.id)
