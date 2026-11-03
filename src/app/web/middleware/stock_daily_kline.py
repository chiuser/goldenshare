"""The single HTTP path using direct ASGI forwarding for indicator sending."""


def is_stock_daily_kline(scope) -> bool:
    return (scope["type"] == "http" and scope["method"] == "GET"
            and scope["path"] == "/api/v1/wealth/market/stock-detail/kline")
