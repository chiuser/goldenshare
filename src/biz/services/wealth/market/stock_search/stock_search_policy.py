from __future__ import annotations

from dataclasses import dataclass


DEFAULT_STOCK_SEARCH_LIMIT = 8
MAX_STOCK_SEARCH_LIMIT = 20
MAX_STOCK_SEARCH_KEYWORD_LENGTH = 32
A_SHARE_EXCHANGES = ("SSE", "SZSE", "BSE")


class StockSearchRequestError(ValueError):
    """Raised when the stock search request violates the public contract."""


@dataclass(frozen=True, slots=True)
class NormalizedStockSearchRequest:
    keyword: str
    escaped_prefix: str
    limit: int


class StockSearchPolicy:
    def normalize(self, *, keyword: str, limit: int) -> NormalizedStockSearchRequest:
        normalized_keyword = keyword.strip().upper()
        if not normalized_keyword:
            raise StockSearchRequestError("搜索关键词不能为空")
        if len(normalized_keyword) > MAX_STOCK_SEARCH_KEYWORD_LENGTH:
            raise StockSearchRequestError(
                f"搜索关键词不能超过 {MAX_STOCK_SEARCH_KEYWORD_LENGTH} 个字符"
            )
        if not 1 <= limit <= MAX_STOCK_SEARCH_LIMIT:
            raise StockSearchRequestError(
                f"搜索结果数量必须在 1 到 {MAX_STOCK_SEARCH_LIMIT} 之间"
            )

        escaped_keyword = (
            normalized_keyword.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        return NormalizedStockSearchRequest(
            keyword=normalized_keyword,
            escaped_prefix=f"{escaped_keyword}%",
            limit=limit,
        )
