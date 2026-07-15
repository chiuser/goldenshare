from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ReviewActiveIndexItem(BaseModel):
    resource: str
    ts_code: str
    index_name: str | None = None
    market: str | None = None
    publisher: str | None = None
    data_status: str
    missing_layers: list[str]
    latest_daily_date: date | None = None
    latest_weekly_date: date | None = None
    latest_monthly_date: date | None = None
    latest_raw_trade_date: date | None = None
    source_serviceability_status: str | None = None
    source_serviceability_label: str | None = None
    source_serviceability_action: str | None = None
    serviceability_reference_date: date | None = None
    source_serviceability_reason: str | None = None
    first_seen_date: date
    last_seen_date: date
    last_checked_at: datetime


class ReviewActiveIndexListResponse(BaseModel):
    total: int
    items: list[ReviewActiveIndexItem]


class ReviewActiveIndexSummaryResponse(BaseModel):
    active_count: int
    daily_available_count: int
    weekly_available_count: int
    monthly_available_count: int
    pending_count: int


class ReviewActiveEtfItem(BaseModel):
    resource: str
    ts_code: str
    csname: str | None = None
    extname: str | None = None
    cname: str | None = None
    exchange: str | None = None
    etf_type: str | None = None
    list_date: date | None = None
    list_status: str | None = None
    latest_fund_daily_date: date | None = None
    data_status: str
    first_seen_date: date
    last_seen_date: date
    last_checked_at: datetime


class ReviewActiveEtfListResponse(BaseModel):
    total: int
    items: list[ReviewActiveEtfItem]


class ReviewActiveEtfSummaryResponse(BaseModel):
    active_count: int
    fund_daily_available_count: int
    pending_count: int


class ReviewActiveIndexCandidateItem(BaseModel):
    ts_code: str
    index_name: str | None = None
    market: str | None = None
    publisher: str | None = None
    exp_date: date | None = None
    eligible_for_activation: bool | None = None
    eligibility_message: str | None = None
    latest_raw_trade_date: date | None = None
    serviceability_reference_date: date | None = None


class ReviewActiveIndexCandidateResponse(BaseModel):
    items: list[ReviewActiveIndexCandidateItem]


class CreateReviewActiveIndexRequest(BaseModel):
    ts_code: str
    resource: str = "index_daily"


class ReviewActiveIndexMutationResponse(BaseModel):
    resource: str
    ts_code: str


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
