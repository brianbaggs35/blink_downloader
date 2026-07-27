"""HTTP API surface, assembled under the /api prefix."""

from fastapi import APIRouter

from app.api.ai_stats import router as ai_stats_router
from app.api.alerts import router as alerts_router
from app.api.biometrics import router as biometrics_router
from app.api.blink import router as blink_router
from app.api.cameras import router as cameras_router
from app.api.clips import router as clips_router
from app.api.health import router as health_router
from app.api.integrations import router as integrations_router
from app.api.livefeed import router as livefeed_router
from app.api.settings import router as settings_router
from app.api.setup import router as setup_router
from app.api.storage import router as storage_router
from app.api.users_admin import router as users_admin_router
from app.api.vehicles import router as vehicles_router
from app.users.auth import auth_backend, fastapi_users
from app.users.schemas import UserRead, UserUpdate

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router, tags=["health"])
api_router.include_router(setup_router, tags=["setup"])
api_router.include_router(
    fastapi_users.get_auth_router(auth_backend), prefix="/auth", tags=["auth"]
)
api_router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"]
)
api_router.include_router(users_admin_router)
api_router.include_router(biometrics_router)
api_router.include_router(blink_router)
api_router.include_router(cameras_router)
api_router.include_router(clips_router)
api_router.include_router(livefeed_router)
api_router.include_router(settings_router)
api_router.include_router(vehicles_router)
api_router.include_router(alerts_router)
api_router.include_router(ai_stats_router)
api_router.include_router(integrations_router)
api_router.include_router(storage_router)
