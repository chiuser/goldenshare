from __future__ import annotations

# Deprecated compatibility shim:
# platform -> biz split phase 1 migrated main implementation to src.biz.queries.share_market_query_service.
from src.biz.queries.share_market_query_service import ShareMarketQueryService, safe_build_market_overview

__all__ = ["ShareMarketQueryService", "safe_build_market_overview"]
