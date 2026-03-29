from __future__ import annotations

from fastapi import APIRouter

from src.web.api.v1 import admin, auth, health, users


router = APIRouter(prefix="/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(admin.router)
