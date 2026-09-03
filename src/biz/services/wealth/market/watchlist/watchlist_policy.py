from __future__ import annotations

from dataclasses import dataclass

DEFAULT_WATCHLIST_PAGE_SIZE = 100
MAX_WATCHLIST_PAGE_SIZE = 200


class WatchlistRequestError(ValueError):
    """A request violates the watchlist contract."""


class WatchlistStockNotEligibleError(ValueError):
    """Only currently listed A-share equities can be added."""


@dataclass(frozen=True, slots=True)
class WatchlistPageRequest:
    limit: int
    after_id: int | None


class WatchlistPolicy:
    def normalize_ts_code(self, ts_code: str) -> str:
        code = ts_code.strip().upper()
        if not 1 <= len(code) <= 16:
            raise WatchlistRequestError("股票代码长度必须为 1 到 16 个字符")
        return code

    def normalize_page(
        self, *, limit: int, after_id: int | None
    ) -> WatchlistPageRequest:
        if not 1 <= limit <= MAX_WATCHLIST_PAGE_SIZE:
            raise WatchlistRequestError("每批数量必须在 1 到 200 之间")
        if after_id is not None and not 1 <= after_id <= 9223372036854775807:
            raise WatchlistRequestError("分页游标必须是有效正整数")
        return WatchlistPageRequest(limit, after_id)
