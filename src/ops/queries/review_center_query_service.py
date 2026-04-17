from __future__ import annotations

from datetime import date

from sqlalchemy import and_, case, desc, false, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.ths_index import ThsIndex
from src.foundation.models.core.ths_member import ThsMember
from src.foundation.models.core_serving.security_serving import Security
from src.ops.models.ops.index_series_active import IndexSeriesActive
from src.ops.schemas.review_center import (
    ReviewActiveIndexItem,
    ReviewActiveIndexListResponse,
    ReviewBoardMemberItem,
    ReviewDcBoardItem,
    ReviewDcBoardListResponse,
    ReviewEquityBoardItem,
    ReviewEquityBoardMembershipItem,
    ReviewEquityBoardMembershipListResponse,
    ReviewEquitySuggestItem,
    ReviewEquitySuggestResponse,
    ReviewThsBoardItem,
    ReviewThsBoardListResponse,
)


class ReviewCenterQueryService:
    def list_active_indexes(
        self,
        session: Session,
        *,
        resource: str = "index_daily",
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> ReviewActiveIndexListResponse:
        page_size = max(1, min(page_size, 500))
        page = max(1, page)
        offset = (page - 1) * page_size

        stmt = (
            select(
                IndexSeriesActive.resource.label("resource"),
                IndexSeriesActive.ts_code.label("ts_code"),
                IndexSeriesActive.first_seen_date.label("first_seen_date"),
                IndexSeriesActive.last_seen_date.label("last_seen_date"),
                IndexSeriesActive.last_checked_at.label("last_checked_at"),
                IndexBasic.name.label("index_name"),
            )
            .select_from(IndexSeriesActive)
            .outerjoin(IndexBasic, IndexBasic.ts_code == IndexSeriesActive.ts_code)
            .where(IndexSeriesActive.resource == resource)
        )
        if keyword:
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(IndexSeriesActive.ts_code.ilike(pattern), IndexBasic.name.ilike(pattern)))

        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = session.execute(
            stmt.order_by(IndexSeriesActive.ts_code.asc()).limit(page_size).offset(offset)
        ).all()
        return ReviewActiveIndexListResponse(
            total=int(total),
            items=[
                ReviewActiveIndexItem(
                    resource=row.resource,
                    ts_code=row.ts_code,
                    index_name=row.index_name,
                    first_seen_date=row.first_seen_date,
                    last_seen_date=row.last_seen_date,
                    last_checked_at=row.last_checked_at,
                )
                for row in rows
            ],
        )

    def list_ths_boards(
        self,
        session: Session,
        *,
        board_type: str | None = None,
        keyword: str | None = None,
        min_constituent_count: int = 0,
        include_members: bool = True,
        page: int = 1,
        page_size: int = 30,
    ) -> ReviewThsBoardListResponse:
        page_size = max(1, min(page_size, 200))
        page = max(1, page)
        offset = (page - 1) * page_size

        ths_count_subq = (
            select(
                ThsMember.ts_code.label("board_code"),
                func.count(func.distinct(ThsMember.con_code)).label("constituent_count"),
            )
            .where(ThsMember.out_date.is_(None))
            .group_by(ThsMember.ts_code)
            .subquery("ths_count_subq")
        )
        count_expr = func.coalesce(ths_count_subq.c.constituent_count, 0)
        stmt = (
            select(
                ThsIndex.ts_code.label("board_code"),
                ThsIndex.name.label("board_name"),
                ThsIndex.exchange.label("exchange"),
                ThsIndex.type_.label("board_type"),
                count_expr.label("constituent_count"),
            )
            .select_from(ThsIndex)
            .outerjoin(ths_count_subq, ths_count_subq.c.board_code == ThsIndex.ts_code)
        )
        if board_type:
            stmt = stmt.where(ThsIndex.type_ == board_type)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(ThsIndex.ts_code.ilike(pattern), ThsIndex.name.ilike(pattern)))
        if min_constituent_count > 0:
            stmt = stmt.where(count_expr >= min_constituent_count)

        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = session.execute(
            stmt.order_by(
                desc(count_expr),
                ThsIndex.ts_code.asc(),
            ).limit(page_size).offset(offset)
        ).all()
        board_codes = [row.board_code for row in rows]
        members_by_board: dict[str, list[ReviewBoardMemberItem]] = {code: [] for code in board_codes}
        if include_members and board_codes:
            member_rows = session.execute(
                select(
                    ThsMember.ts_code,
                    ThsMember.con_code,
                    ThsMember.con_name,
                    ThsMember.in_date,
                    ThsMember.out_date,
                )
                .where(ThsMember.ts_code.in_(board_codes))
                .where(ThsMember.out_date.is_(None))
                .order_by(ThsMember.ts_code.asc(), ThsMember.con_code.asc())
            ).all()
            for row in member_rows:
                members_by_board[row.ts_code].append(
                    ReviewBoardMemberItem(
                        ts_code=row.con_code,
                        name=row.con_name,
                        in_date=row.in_date,
                        out_date=row.out_date,
                    )
                )

        return ReviewThsBoardListResponse(
            total=int(total),
            items=[
                ReviewThsBoardItem(
                    board_code=row.board_code,
                    board_name=row.board_name,
                    exchange=row.exchange,
                    board_type=row.board_type,
                    constituent_count=int(row.constituent_count or 0),
                    members=members_by_board.get(row.board_code, []),
                )
                for row in rows
            ],
        )

    def list_dc_boards(
        self,
        session: Session,
        *,
        trade_date: date | None = None,
        idx_type: str | None = None,
        keyword: str | None = None,
        min_constituent_count: int = 0,
        include_members: bool = True,
        page: int = 1,
        page_size: int = 30,
    ) -> ReviewDcBoardListResponse:
        page_size = max(1, min(page_size, 200))
        page = max(1, page)
        offset = (page - 1) * page_size
        resolved_trade_date = trade_date or session.scalar(select(func.max(DcIndex.trade_date)))
        if resolved_trade_date is None:
            return ReviewDcBoardListResponse(trade_date=None, idx_type_options=[], total=0, items=[])

        idx_type_options = [
            row[0]
            for row in session.execute(
                select(DcIndex.idx_type)
                .where(DcIndex.trade_date == resolved_trade_date)
                .where(DcIndex.idx_type.is_not(None))
                .distinct()
                .order_by(DcIndex.idx_type.asc())
            ).all()
            if row[0]
        ]

        dc_count_subq = (
            select(
                DcMember.ts_code.label("board_code"),
                func.count(func.distinct(DcMember.con_code)).label("constituent_count"),
            )
            .where(DcMember.trade_date == resolved_trade_date)
            .group_by(DcMember.ts_code)
            .subquery("dc_count_subq")
        )
        count_expr = func.coalesce(dc_count_subq.c.constituent_count, 0)
        stmt = (
            select(
                DcIndex.ts_code.label("board_code"),
                DcIndex.name.label("board_name"),
                DcIndex.idx_type.label("idx_type"),
                count_expr.label("constituent_count"),
            )
            .select_from(DcIndex)
            .outerjoin(dc_count_subq, dc_count_subq.c.board_code == DcIndex.ts_code)
            .where(DcIndex.trade_date == resolved_trade_date)
        )
        if idx_type:
            stmt = stmt.where(DcIndex.idx_type == idx_type)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(DcIndex.ts_code.ilike(pattern), DcIndex.name.ilike(pattern)))
        if min_constituent_count > 0:
            stmt = stmt.where(count_expr >= min_constituent_count)

        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = session.execute(
            stmt.order_by(
                desc(count_expr),
                DcIndex.ts_code.asc(),
            ).limit(page_size).offset(offset)
        ).all()
        board_codes = [row.board_code for row in rows]
        members_by_board: dict[str, list[ReviewBoardMemberItem]] = {code: [] for code in board_codes}
        if include_members and board_codes:
            member_rows = session.execute(
                select(
                    DcMember.ts_code,
                    DcMember.con_code,
                    DcMember.name,
                )
                .where(DcMember.trade_date == resolved_trade_date)
                .where(DcMember.ts_code.in_(board_codes))
                .order_by(DcMember.ts_code.asc(), DcMember.con_code.asc())
            ).all()
            for row in member_rows:
                members_by_board[row.ts_code].append(
                    ReviewBoardMemberItem(
                        ts_code=row.con_code,
                        name=row.name,
                    )
                )

        return ReviewDcBoardListResponse(
            trade_date=resolved_trade_date,
            idx_type_options=idx_type_options,
            total=int(total),
            items=[
                ReviewDcBoardItem(
                    board_code=row.board_code,
                    board_name=row.board_name,
                    idx_type=row.idx_type,
                    constituent_count=int(row.constituent_count or 0),
                    members=members_by_board.get(row.board_code, []),
                )
                for row in rows
            ],
        )

    def suggest_equities(
        self,
        session: Session,
        *,
        keyword: str,
        limit: int = 20,
    ) -> ReviewEquitySuggestResponse:
        normalized_keyword = keyword.strip()
        if not normalized_keyword:
            return ReviewEquitySuggestResponse(items=[])
        limit = max(1, min(limit, 50))
        prefix_pattern = f"{normalized_keyword}%"
        contains_pattern = f"%{normalized_keyword}%"
        score_expr = case(
            (Security.ts_code.ilike(prefix_pattern), 0),
            (Security.symbol.ilike(prefix_pattern), 1),
            (Security.cnspell.ilike(prefix_pattern), 2),
            (Security.name.ilike(prefix_pattern), 3),
            else_=4,
        )
        rows = session.execute(
            select(Security.ts_code, Security.name)
            .where(Security.security_type == "EQUITY")
            .where(
                or_(
                    Security.ts_code.ilike(prefix_pattern),
                    Security.symbol.ilike(prefix_pattern),
                    Security.cnspell.ilike(prefix_pattern),
                    Security.name.ilike(contains_pattern),
                )
            )
            .order_by(score_expr.asc(), Security.ts_code.asc())
            .limit(limit)
        ).all()
        return ReviewEquitySuggestResponse(
            items=[ReviewEquitySuggestItem(ts_code=row.ts_code, name=row.name) for row in rows],
        )

    def list_equity_membership(
        self,
        session: Session,
        *,
        trade_date: date | None = None,
        keyword: str | None = None,
        min_board_count: int = 0,
        provider: str = "all",
        page: int = 1,
        page_size: int = 30,
    ) -> ReviewEquityBoardMembershipListResponse:
        page_size = max(1, min(page_size, 200))
        page = max(1, page)
        offset = (page - 1) * page_size
        resolved_provider = (provider or "all").lower()
        if resolved_provider not in {"all", "ths", "dc"}:
            resolved_provider = "all"

        resolved_trade_date = trade_date or session.scalar(select(func.max(DcIndex.trade_date)))

        ths_stmt = (
            select(
                ThsMember.con_code.label("ts_code"),
                ThsMember.con_name.label("fallback_name"),
                literal("ths").label("provider"),
                ThsMember.ts_code.label("board_code"),
                ThsIndex.name.label("board_name"),
            )
            .select_from(ThsMember)
            .join(ThsIndex, ThsIndex.ts_code == ThsMember.ts_code)
            .where(ThsMember.out_date.is_(None))
        )

        dc_stmt = (
            select(
                DcMember.con_code.label("ts_code"),
                DcMember.name.label("fallback_name"),
                literal("dc").label("provider"),
                DcMember.ts_code.label("board_code"),
                DcIndex.name.label("board_name"),
            )
            .select_from(DcMember)
            .join(
                DcIndex,
                and_(
                    DcIndex.ts_code == DcMember.ts_code,
                    DcIndex.trade_date == DcMember.trade_date,
                ),
            )
        )
        if resolved_trade_date is not None:
            dc_stmt = dc_stmt.where(DcMember.trade_date == resolved_trade_date)
        else:
            dc_stmt = dc_stmt.where(false())

        if resolved_provider == "ths":
            membership_subq = ths_stmt.subquery("membership_source")
        elif resolved_provider == "dc":
            membership_subq = dc_stmt.subquery("membership_source")
        else:
            membership_subq = union_all(ths_stmt, dc_stmt).subquery("membership_source")

        board_key_expr = membership_subq.c.provider + literal(":") + membership_subq.c.board_code
        board_count_expr = func.count(func.distinct(board_key_expr))
        equity_name_expr = func.coalesce(func.max(Security.name), func.max(membership_subq.c.fallback_name))
        summary_stmt = (
            select(
                membership_subq.c.ts_code.label("ts_code"),
                equity_name_expr.label("equity_name"),
                board_count_expr.label("board_count"),
            )
            .select_from(membership_subq)
            .outerjoin(Security, Security.ts_code == membership_subq.c.ts_code)
            .group_by(membership_subq.c.ts_code)
        )
        if keyword:
            normalized_keyword = keyword.strip()
            pattern = f"%{normalized_keyword}%"
            prefix_pattern = f"{normalized_keyword}%"
            summary_stmt = summary_stmt.having(
                or_(
                    membership_subq.c.ts_code.ilike(pattern),
                    equity_name_expr.ilike(pattern),
                    func.max(Security.symbol).ilike(prefix_pattern),
                    func.max(Security.cnspell).ilike(prefix_pattern),
                )
            )
        if min_board_count > 0:
            summary_stmt = summary_stmt.having(board_count_expr >= min_board_count)

        total = session.scalar(select(func.count()).select_from(summary_stmt.subquery())) or 0
        summary_rows = session.execute(
            summary_stmt.order_by(desc(board_count_expr), membership_subq.c.ts_code.asc())
            .limit(page_size)
            .offset(offset)
        ).all()
        equity_codes = [row.ts_code for row in summary_rows]

        boards_by_equity: dict[str, list[ReviewEquityBoardItem]] = {code: [] for code in equity_codes}
        if equity_codes:
            detail_rows = session.execute(
                select(
                    membership_subq.c.ts_code,
                    membership_subq.c.provider,
                    membership_subq.c.board_code,
                    membership_subq.c.board_name,
                )
                .where(membership_subq.c.ts_code.in_(equity_codes))
                .distinct()
                .order_by(
                    membership_subq.c.ts_code.asc(),
                    membership_subq.c.provider.asc(),
                    membership_subq.c.board_code.asc(),
                )
            ).all()
            for row in detail_rows:
                boards_by_equity[row.ts_code].append(
                    ReviewEquityBoardItem(
                        provider=row.provider,
                        board_code=row.board_code,
                        board_name=row.board_name,
                    )
                )

        return ReviewEquityBoardMembershipListResponse(
            dc_trade_date=resolved_trade_date,
            total=int(total),
            items=[
                ReviewEquityBoardMembershipItem(
                    ts_code=row.ts_code,
                    equity_name=row.equity_name,
                    board_count=int(row.board_count or 0),
                    boards=boards_by_equity.get(row.ts_code, []),
                )
                for row in summary_rows
            ],
        )
