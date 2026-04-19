from __future__ import annotations

from fastapi import APIRouter

from src.app.api.v1 import health
from src.platform.api.v1 import admin, admin_users, auth, share, users
from src.biz.api import market as biz_market
from src.biz.api import quote as biz_quote
from src.ops.api.router import router as ops_router


router = APIRouter(prefix="/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(admin.router)
router.include_router(admin_users.router)
router.include_router(ops_router)
router.include_router(share.router)
router.include_router(biz_quote.router)
router.include_router(biz_market.router)
