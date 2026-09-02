from __future__ import annotations

from fastapi import APIRouter

from src.app.api.v1 import health, qtf
from src.app.auth.api import admin, admin_users, auth, users
from src.biz.api import market as biz_market
from src.biz.api import quote as biz_quote
from src.biz.api import realtime as biz_realtime
from src.biz.api.wealth.market import breadth as wealth_market_breadth
from src.biz.api.wealth.market import context as wealth_market_context
from src.biz.api.wealth.market import index_detail as wealth_market_index_detail
from src.biz.api.wealth.market import (
    index_detail_nine_turn as wealth_market_index_detail_nine_turn,
)
from src.biz.api.wealth.market import leaderboards as wealth_market_leaderboards
from src.biz.api.wealth.market import limit_up as wealth_market_limit_up
from src.biz.api.wealth.market import major_indices as wealth_market_major_indices
from src.biz.api.wealth.market import money_flow as wealth_market_money_flow
from src.biz.api.wealth.market import news_briefs as wealth_market_news_briefs
from src.biz.api.wealth.market import news_communications as wealth_market_news_communications
from src.biz.api.wealth.market import news_item as wealth_market_news_item
from src.biz.api.wealth.market import sector_overview as wealth_market_sector_overview
from src.biz.api.wealth.market import sector_analysis as wealth_market_sector_analysis
from src.biz.api.wealth.market import stock_detail as wealth_market_stock_detail
from src.biz.api.wealth.market import stock_detail_news as wealth_market_stock_detail_news
from src.biz.api.wealth.market import stock_detail_nine_turn as wealth_market_stock_detail_nine_turn
from src.biz.api.wealth.market import stock_search as wealth_market_stock_search
from src.biz.api.wealth.market import streak_ladder as wealth_market_streak_ladder
from src.biz.api.wealth.market import style as wealth_market_style
from src.biz.api.wealth.market import summary as wealth_market_summary
from src.biz.api.wealth.market import turnover as wealth_market_turnover
from src.biz.api.wealth.market import turnover_insight as wealth_market_turnover_insight
from src.foundation.config.local_minute_capability import (
    resolve_index_minute_capability,
    resolve_index_nine_turn_minute_capability,
    resolve_local_minute_capability,
    resolve_stock_nine_turn_minute_capability,
)
from src.foundation.config.settings import get_settings
from src.foundation.config.stock_daily_trend_channel_capability import (
    resolve_stock_daily_trend_channel_capability,
)
from src.ops.api.router import router as ops_router

router = APIRouter(prefix="/v1")
router.include_router(health.router)
router.include_router(qtf.router)
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(admin.router)
router.include_router(admin_users.router)
router.include_router(ops_router)
router.include_router(biz_quote.router)
router.include_router(biz_market.router)
router.include_router(biz_realtime.router)
router.include_router(wealth_market_context.router)
router.include_router(wealth_market_index_detail.router)
router.include_router(wealth_market_index_detail_nine_turn.router)
router.include_router(wealth_market_summary.router)
router.include_router(wealth_market_major_indices.router)
router.include_router(wealth_market_breadth.router)
router.include_router(wealth_market_style.router)
router.include_router(wealth_market_turnover.router)
router.include_router(wealth_market_turnover_insight.router)
router.include_router(wealth_market_money_flow.router)
router.include_router(wealth_market_leaderboards.router)
router.include_router(wealth_market_limit_up.router)
router.include_router(wealth_market_streak_ladder.router)
router.include_router(wealth_market_stock_detail.router)
router.include_router(wealth_market_stock_detail_news.router)
router.include_router(wealth_market_stock_detail_nine_turn.router)
router.include_router(wealth_market_stock_search.router)
router.include_router(wealth_market_sector_overview.router)
router.include_router(wealth_market_sector_analysis.router)
router.include_router(wealth_market_news_briefs.router)
router.include_router(wealth_market_news_communications.router)
router.include_router(wealth_market_news_item.router)


def _include_local_minute_router(target_router: APIRouter) -> None:
    capability = resolve_local_minute_capability(get_settings())
    if capability.enabled:
        from src.biz.api.wealth.market import stock_detail_minutes

        target_router.include_router(stock_detail_minutes.router)

    stock_nine_turn_capability = resolve_stock_nine_turn_minute_capability(
        get_settings()
    )
    if stock_nine_turn_capability.enabled:
        from src.biz.api.wealth.market import stock_detail_minute_nine_turn

        target_router.include_router(stock_detail_minute_nine_turn.router)

    index_capability = resolve_index_minute_capability(get_settings())
    if index_capability.enabled:
        from src.biz.api.wealth.market import index_detail_minutes

        target_router.include_router(index_detail_minutes.router)

    index_nine_turn_capability = resolve_index_nine_turn_minute_capability(
        get_settings()
    )
    if index_nine_turn_capability.enabled:
        from src.biz.api.wealth.market import index_detail_minute_nine_turn

        target_router.include_router(index_detail_minute_nine_turn.router)


_include_local_minute_router(router)


def _include_local_stock_daily_trend_channel_router(
    target_router: APIRouter,
) -> None:
    capability = resolve_stock_daily_trend_channel_capability(get_settings())
    if not capability.enabled:
        return
    from src.biz.api.wealth.market import stock_detail_trend_channel

    target_router.include_router(stock_detail_trend_channel.router)


_include_local_stock_daily_trend_channel_router(router)
