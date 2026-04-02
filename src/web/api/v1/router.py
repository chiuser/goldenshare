from __future__ import annotations

from fastapi import APIRouter

from src.web.api.v1 import admin, auth, health, share, users
from src.web.api.v1.ops import router as ops_router


router = APIRouter(prefix="/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(admin.router)
router.include_router(ops_router)
router.include_router(share.router)
