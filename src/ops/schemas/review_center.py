from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ReviewActiveIndexItem(BaseModel):
    resource: str
    ts_code: str
    index_name: str | None = None
    first_seen_date: date
    last_seen_date: date
    last_checked_at: datetime


class ReviewActiveIndexListResponse(BaseModel):
    total: int
    items: list[ReviewActiveIndexItem]


class ReviewBoardMemberItem(BaseModel):
    ts_code: str
    name: str | None
    in_date: date | None = None
    out_date: date | None = None


class ReviewThsBoardItem(BaseModel):
    board_code: str
    board_name: str | None
    exchange: str | None
    board_type: str | None
    constituent_count: int
    members: list[ReviewBoardMemberItem]


class ReviewThsBoardListResponse(BaseModel):
    total: int
    items: list[ReviewThsBoardItem]


class ReviewDcBoardItem(BaseModel):
    board_code: str
    board_name: str | None
    idx_type: str | None
    constituent_count: int
    members: list[ReviewBoardMemberItem]


class ReviewDcBoardListResponse(BaseModel):
    trade_date: date | None
    idx_type_options: list[str]
    total: int
    items: list[ReviewDcBoardItem]


class ReviewEquityBoardItem(BaseModel):
    provider: str
    board_code: str
    board_name: str | None


class ReviewEquityBoardMembershipItem(BaseModel):
    ts_code: str
    equity_name: str | None
    board_count: int
    boards: list[ReviewEquityBoardItem]


class ReviewEquityBoardMembershipListResponse(BaseModel):
    dc_trade_date: date | None
    total: int
    items: list[ReviewEquityBoardMembershipItem]


class ReviewEquitySuggestItem(BaseModel):
    ts_code: str
    name: str | None


class ReviewEquitySuggestResponse(BaseModel):
    items: list[ReviewEquitySuggestItem]
