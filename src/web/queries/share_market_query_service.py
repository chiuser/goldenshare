from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.web.schemas.share import ShareMarketOverviewResponse, ShareMarketRow, ShareMarketSummary


SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(name: str) -> str:
    if not SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name}")
    return f'"{name}"'


class ShareMarketQueryService:
    def build_market_overview(self, session: Session, *, limit: int = 8) -> ShareMarketOverviewResponse:
        clamped_limit = max(1, min(limit, 30))
        columns = self._load_dm_columns(session)
        if not columns:
            return ShareMarketOverviewResponse(
                available=False,
                unavailable_reason="当前环境还没有 dm.equity_daily_snapshot。请先执行一次“同步数据集市”。",
            )

        ts_code_col = self._pick(columns, "ts_code")
        if ts_code_col is None:
            return ShareMarketOverviewResponse(
                available=False,
                unavailable_reason="dm.equity_daily_snapshot 缺少 ts_code 字段，暂时无法展示行情快照。",
            )

        name_col = self._pick(columns, "name", "security_name", "stock_name")
        trade_date_col = self._pick(columns, "trade_date", "biz_date", "date")
        close_col = self._pick(columns, "close")
        pct_change_col = self._pick(columns, "pct_change", "pct_chg", "change_pct")
        amount_col = self._pick(columns, "amount", "turnover")

        summary = self._build_summary(
            session,
            ts_code_col=ts_code_col,
            trade_date_col=trade_date_col,
            pct_change_col=pct_change_col,
            amount_col=amount_col,
        )

        row_sql_columns = {
            "ts_code": ts_code_col,
            "name": name_col,
            "trade_date": trade_date_col,
            "close": close_col,
            "pct_change": pct_change_col,
            "amount": amount_col,
        }

        top_by_amount = self._query_rows(
            session,
            columns=row_sql_columns,
            order_by=amount_col,
            descending=True,
            limit=clamped_limit,
        ) if amount_col else []
        top_gainers = self._query_rows(
            session,
            columns=row_sql_columns,
            order_by=pct_change_col,
            descending=True,
            limit=clamped_limit,
        ) if pct_change_col else []
        top_losers = self._query_rows(
            session,
            columns=row_sql_columns,
            order_by=pct_change_col,
            descending=False,
            limit=clamped_limit,
        ) if pct_change_col else []

        return ShareMarketOverviewResponse(
            available=True,
            summary=summary,
            top_by_amount=top_by_amount,
            top_gainers=top_gainers,
            top_losers=top_losers,
        )

    @staticmethod
    def _pick(columns: set[str], *candidates: str) -> str | None:
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return None

    @staticmethod
    def _load_dm_columns(session: Session) -> set[str]:
        stmt = text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'dm'
              AND table_name = 'equity_daily_snapshot'
            """
        )
        return {str(row[0]) for row in session.execute(stmt)}

    def _build_summary(
        self,
        session: Session,
        *,
        ts_code_col: str,
        trade_date_col: str | None,
        pct_change_col: str | None,
        amount_col: str | None,
    ) -> ShareMarketSummary:
        select_parts: list[str] = [f"COUNT({_safe_identifier(ts_code_col)})::bigint AS total_symbols"]
        if trade_date_col:
            select_parts.append(f"MAX({_safe_identifier(trade_date_col)}) AS as_of_date")
        else:
            select_parts.append("NULL::date AS as_of_date")

        if pct_change_col:
            pct_ref = _safe_identifier(pct_change_col)
            select_parts.extend(
                [
                    f"SUM(CASE WHEN {pct_ref} > 0 THEN 1 ELSE 0 END)::bigint AS up_count",
                    f"SUM(CASE WHEN {pct_ref} < 0 THEN 1 ELSE 0 END)::bigint AS down_count",
                    f"SUM(CASE WHEN {pct_ref} = 0 THEN 1 ELSE 0 END)::bigint AS flat_count",
                    f"AVG({pct_ref})::numeric AS avg_pct_change",
                ]
            )
        else:
            select_parts.extend(
                [
                    "NULL::bigint AS up_count",
                    "NULL::bigint AS down_count",
                    "NULL::bigint AS flat_count",
                    "NULL::numeric AS avg_pct_change",
                ]
            )

        if amount_col:
            select_parts.append(f"SUM({_safe_identifier(amount_col)})::numeric AS total_amount")
        else:
            select_parts.append("NULL::numeric AS total_amount")

        stmt = text(
            f"""
            SELECT {", ".join(select_parts)}
            FROM dm.equity_daily_snapshot
            """
        )
        row = session.execute(stmt).mappings().one()
        return ShareMarketSummary(
            as_of_date=row.get("as_of_date"),
            total_symbols=int(row.get("total_symbols") or 0),
            up_count=int(row["up_count"]) if row.get("up_count") is not None else None,
            down_count=int(row["down_count"]) if row.get("down_count") is not None else None,
            flat_count=int(row["flat_count"]) if row.get("flat_count") is not None else None,
            avg_pct_change=Decimal(str(row["avg_pct_change"])) if row.get("avg_pct_change") is not None else None,
            total_amount=Decimal(str(row["total_amount"])) if row.get("total_amount") is not None else None,
        )

    def _query_rows(
        self,
        session: Session,
        *,
        columns: dict[str, str | None],
        order_by: str | None,
        descending: bool,
        limit: int,
    ) -> list[ShareMarketRow]:
        if order_by is None:
            return []

        select_parts: list[str] = []
        for alias, column in columns.items():
            if column is None:
                select_parts.append(f"NULL AS {alias}")
            else:
                select_parts.append(f"{_safe_identifier(column)} AS {alias}")
        direction = "DESC" if descending else "ASC"
        stmt = text(
            f"""
            SELECT {", ".join(select_parts)}
            FROM dm.equity_daily_snapshot
            WHERE {_safe_identifier(order_by)} IS NOT NULL
            ORDER BY {_safe_identifier(order_by)} {direction}
            LIMIT :limit
            """
        )
        rows = session.execute(stmt, {"limit": limit}).mappings().all()
        return [
            ShareMarketRow(
                ts_code=str(item.get("ts_code")),
                name=str(item["name"]) if item.get("name") is not None else None,
                trade_date=item.get("trade_date"),
                close=Decimal(str(item["close"])) if item.get("close") is not None else None,
                pct_change=Decimal(str(item["pct_change"])) if item.get("pct_change") is not None else None,
                amount=Decimal(str(item["amount"])) if item.get("amount") is not None else None,
            )
            for item in rows
            if item.get("ts_code") is not None
        ]


def safe_build_market_overview(session: Session, *, limit: int = 8) -> ShareMarketOverviewResponse:
    try:
        return ShareMarketQueryService().build_market_overview(session, limit=limit)
    except SQLAlchemyError as exc:
        return ShareMarketOverviewResponse(
            available=False,
            unavailable_reason=f"读取 dm.equity_daily_snapshot 失败：{exc.__class__.__name__}",
        )
