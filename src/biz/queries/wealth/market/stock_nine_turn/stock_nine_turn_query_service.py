from __future__ import annotations

import base64
import binascii
from datetime import date
import json

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.stock_nine_turn.stock_nine_turn_query import (
    StockNineTurnQuery,
)
from src.biz.schemas.wealth.market.nine_turn import NineTurnSeriesDto
from src.biz.services.wealth.market.nine_turn.nine_turn_response_policy import (
    NineTurnContractError,
    build_stock_nine_turn_response,
)
from src.foundation.models.core_serving.security_serving import Security


class StockNineTurnRequestError(ValueError):
    pass


class StockNineTurnNotFoundError(ValueError):
    pass


class StockNineTurnSourceContractError(RuntimeError):
    pass


class StockNineTurnQueryError(RuntimeError):
    pass


class StockNineTurnQueryService:
    def __init__(self) -> None:
        self._context_query = MarketPageContextQuery()
        self._query = StockNineTurnQuery()

    def read_daily(
        self,
        session: Session,
        *,
        ts_code: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        cursor: str | None,
        debug: bool,
    ) -> NineTurnSeriesDto:
        normalized_code = ts_code.strip().upper()
        security = session.get(Security, normalized_code)
        if security is None or security.security_type != "EQUITY":
            raise StockNineTurnNotFoundError(f"未找到股票标的：{normalized_code}")
        if not 1 <= limit <= 2_000:
            raise StockNineTurnRequestError("limit 必须在 1 到 2000 之间。")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise StockNineTurnRequestError("startDate 不能晚于 endDate。")
        context = self._context_query.resolve_context(
            session,
            market="CN_A",
            requested_trade_date=end_date,
        )
        query_end_date = end_date or context.trade_date
        before_trade_date = _decode_daily_cursor(
            cursor,
            ts_code=normalized_code,
            start_date=start_date,
            end_date=query_end_date,
        )
        try:
            page = self._query.load_daily_page(
                session,
                ts_code=normalized_code,
                start_date=start_date,
                end_date=query_end_date,
                before_trade_date=before_trade_date,
                limit=limit,
            )
            for row in page.rows:
                if row["nine_turn_matched"] and row["formula_version"] != 1:
                    raise StockNineTurnSourceContractError(
                        "股票日线九转 serving formula_version 不是 1。"
                    )
            source_row_count = len(page.rows)
            matched_row_count = sum(
                1 for row in page.rows if row["nine_turn_matched"]
            )
            next_cursor = None
            if page.has_more and page.rows:
                next_cursor = _encode_daily_cursor(
                    ts_code=normalized_code,
                    start_date=start_date,
                    end_date=query_end_date,
                    before_trade_date=page.rows[0]["trade_date"],
                )
            return build_stock_nine_turn_response(
                ts_code=normalized_code,
                period="day",
                rows=list(page.rows),
                source_row_count=source_row_count,
                matched_row_count=matched_row_count,
                missing_row_count=source_row_count - matched_row_count,
                has_more=page.has_more,
                next_cursor=next_cursor,
                start_date=start_date,
                end_date=query_end_date,
                expected_end_date=query_end_date,
                observed_start_date=page.observed_start_date,
                observed_end_date=page.observed_end_date,
                limit=limit,
                debug_info=(
                    {
                        "sourceTables": [
                            "core_serving.equity_factor_pro",
                            "core_serving.equity_qfq_nineturn_daily",
                        ],
                        "beforeTradeDate": (
                            before_trade_date.isoformat()
                            if before_trade_date is not None
                            else None
                        ),
                    }
                    if debug
                    else None
                ),
            )
        except (StockNineTurnRequestError, StockNineTurnSourceContractError):
            raise
        except NineTurnContractError as exc:
            raise StockNineTurnSourceContractError(str(exc)) from exc
        except SQLAlchemyError as exc:
            raise StockNineTurnQueryError("股票日线九转查询失败。") from exc


def _encode_daily_cursor(
    *,
    ts_code: str,
    start_date: date | None,
    end_date: date,
    before_trade_date: date,
) -> str:
    payload = {
        "v": 1,
        "dataset": "stock_daily_nine_turn",
        "tsCode": ts_code,
        "period": "day",
        "startDate": start_date.isoformat() if start_date else None,
        "endDate": end_date.isoformat(),
        "beforeTradeDate": before_trade_date.isoformat(),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()
    return encoded.rstrip("=")


def _decode_daily_cursor(
    value: str | None,
    *,
    ts_code: str,
    start_date: date | None,
    end_date: date,
) -> date | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise StockNineTurnRequestError("cursor 不合法。") from exc
    expected_keys = {
        "v",
        "dataset",
        "tsCode",
        "period",
        "startDate",
        "endDate",
        "beforeTradeDate",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise StockNineTurnRequestError("cursor 字段不完整或包含未知字段。")
    expected = {
        "v": 1,
        "dataset": "stock_daily_nine_turn",
        "tsCode": ts_code,
        "period": "day",
        "startDate": start_date.isoformat() if start_date else None,
        "endDate": end_date.isoformat(),
    }
    if any(payload.get(key) != expected_value for key, expected_value in expected.items()):
        raise StockNineTurnRequestError("cursor 与当前股票或日期窗口不匹配。")
    try:
        return date.fromisoformat(payload["beforeTradeDate"])
    except (TypeError, ValueError) as exc:
        raise StockNineTurnRequestError("cursor 时间边界不合法。") from exc
