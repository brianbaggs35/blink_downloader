"""HTTP API surface, assembled under the /api prefix."""

from fastapi import APIRouter

from app.api.blink import router as blink_router
from app.api.cameras import router as cameras_router
from app.api.clips import router as clips_router
from app.api.health import router as health_router
from app.api.settings import router as settings_router
from app.api.setup import router as setup_router
from app.api.users_admin import router as users_admin_router
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
api_router.include_router(blink_router)
api_router.include_router(cameras_router)
api_router.include_router(clips_router)
api_router.include_router(settings_router)
