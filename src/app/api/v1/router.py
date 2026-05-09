from __future__ import annotations

from fastapi import APIRouter

from src.app.api.v1 import health
from src.app.auth.api import admin, admin_users, auth, users
from src.biz.api import market as biz_market
from src.biz.api import quote as biz_quote
from src.biz.api.wealth.market import breadth as wealth_market_breadth
from src.biz.api.wealth.market import major_indices as wealth_market_major_indices
from src.biz.api.wealth.market import summary as wealth_market_summary
from src.ops.api.router import router as ops_router


router = APIRouter(prefix="/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(admin.router)
router.include_router(admin_users.router)
router.include_router(ops_router)
router.include_router(biz_quote.router)
router.include_router(biz_market.router)
router.include_router(wealth_market_summary.router)
router.include_router(wealth_market_major_indices.router)
router.include_router(wealth_market_breadth.router)
