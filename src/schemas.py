from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class TushareResponse(BaseModel):
    fields: list[str]
    items: list[list[Any]]

    model_config = ConfigDict(extra="ignore")


class TushareEnvelope(BaseModel):
    code: int
    msg: str
    data: TushareResponse | None = None

    model_config = ConfigDict(extra="ignore")


class SyncResult(BaseModel):
    job_name: str
    run_type: str
    rows_fetched: int = 0
    rows_written: int = 0
    trade_date: date | None = None
    message: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ProBarRequest(BaseModel):
    ts_code: str | None = None
    asset: str = "E"
    start_date: str | None = None
    end_date: str | None = None
    adj: str | None = None
    freq: str = "D"


class DailySnapshotRow(BaseModel):
    ts_code: str
    trade_date: date
    close: Decimal | None = None
