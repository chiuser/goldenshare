from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.wealth_market_turnover_snapshot import WealthMarketTurnoverSnapshot
from src.foundation.models.raw.raw_stk_mins import RawStkMins


TURNOVER_SNAPSHOT_ALLOWED_FREQS: tuple[int, ...] = (1, 5, 15, 30, 60)
TURNOVER_SNAPSHOT_TYPE_STOCK = "stock"
TURNOVER_SNAPSHOT_MARKET_CN_A = "CN_A"
TURNOVER_SNAPSHOT_BUILD_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class TurnoverSnapshotBuildItem:
    trade_date: date
    freq: int
    build_status: str
    latest_trade_time: datetime | None
    security_count: int
    source_row_count: int
    points_count: int
    total_amount: Decimal
    total_vol: Decimal
    build_note: str | None = None


class TurnoverSnapshotMaterializeService:
    """Materialize minute turnover snapshot rows for wealth turnover panel."""

    def materialize_trade_date(
        self,
        session: Session,
        *,
        trade_date: date,
        freqs: list[int] | None = None,
    ) -> list[TurnoverSnapshotBuildItem]:
        normalized_freqs = self._normalize_freqs(freqs)
        results: list[TurnoverSnapshotBuildItem] = []
        for freq in normalized_freqs:
            results.append(self._materialize_one(session, trade_date=trade_date, freq=freq))
        return results

    def _materialize_one(
        self,
        session: Session,
        *,
        trade_date: date,
        freq: int,
    ) -> TurnoverSnapshotBuildItem:
        day_start = datetime.combine(trade_date, time.min)
        day_end = day_start + timedelta(days=1)
        filters = (
            RawStkMins.freq == freq,
            RawStkMins.trade_time >= day_start,
            RawStkMins.trade_time < day_end,
        )

        summary = session.execute(
            select(
                func.count().label("source_row_count"),
                func.count(func.distinct(RawStkMins.ts_code)).label("security_count"),
                func.sum(RawStkMins.amount).label("total_amount"),
                func.sum(RawStkMins.vol).label("total_vol"),
                func.max(RawStkMins.trade_time).label("latest_trade_time"),
            ).where(*filters)
        ).one()

        source_row_count = int(summary.source_row_count or 0)
        security_count = int(summary.security_count or 0)
        total_amount = Decimal(str(summary.total_amount or Decimal("0")))
        total_vol = Decimal(str(summary.total_vol or Decimal("0")))
        latest_trade_time = summary.latest_trade_time

        if source_row_count <= 0 or latest_trade_time is None:
            build_note = f"no raw rows for trade_date={trade_date.isoformat()} freq={freq}"
            existing = session.get(
                WealthMarketTurnoverSnapshot,
                {
                    "type": TURNOVER_SNAPSHOT_TYPE_STOCK,
                    "market": TURNOVER_SNAPSHOT_MARKET_CN_A,
                    "trade_date": trade_date,
                    "freq": freq,
                },
            )
            if existing is not None:
                existing.build_status = "FAILED"
                existing.build_note = build_note
                existing.built_at = datetime.now(timezone.utc)
                existing.build_version = TURNOVER_SNAPSHOT_BUILD_VERSION
            return TurnoverSnapshotBuildItem(
                trade_date=trade_date,
                freq=freq,
                build_status="FAILED",
                latest_trade_time=None,
                security_count=0,
                source_row_count=0,
                points_count=0,
                total_amount=Decimal("0"),
                total_vol=Decimal("0"),
                build_note=build_note,
            )

        points_rows = session.execute(
            select(
                RawStkMins.trade_time.label("trade_time"),
                func.sum(RawStkMins.amount).label("amount"),
                func.sum(RawStkMins.vol).label("vol"),
                func.count(func.distinct(RawStkMins.ts_code)).label("security_count"),
            )
            .where(*filters)
            .group_by(RawStkMins.trade_time)
            .order_by(RawStkMins.trade_time.asc())
        ).all()

        points_json: list[dict[str, object]] = []
        for row in points_rows:
            trade_time = row.trade_time
            if trade_time is None:
                continue
            points_json.append(
                {
                    "tradeTime": trade_time.strftime("%H:%M"),
                    "tradeTimeTs": trade_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "amount": float(row.amount or 0),
                    "vol": float(row.vol or 0),
                    "securityCount": int(row.security_count or 0),
                }
            )

        snapshot = session.get(
            WealthMarketTurnoverSnapshot,
            {
                "type": TURNOVER_SNAPSHOT_TYPE_STOCK,
                "market": TURNOVER_SNAPSHOT_MARKET_CN_A,
                "trade_date": trade_date,
                "freq": freq,
            },
        )
        if snapshot is None:
            snapshot = WealthMarketTurnoverSnapshot(
                type=TURNOVER_SNAPSHOT_TYPE_STOCK,
                market=TURNOVER_SNAPSHOT_MARKET_CN_A,
                trade_date=trade_date,
                freq=freq,
                latest_trade_time=latest_trade_time,
                security_count=security_count,
                source_row_count=source_row_count,
                total_amount=total_amount,
                total_vol=total_vol,
                points_json=points_json,
                build_status="READY",
                build_version=TURNOVER_SNAPSHOT_BUILD_VERSION,
                built_at=datetime.now(timezone.utc),
                build_note=None,
            )
            session.add(snapshot)
        else:
            snapshot.latest_trade_time = latest_trade_time
            snapshot.security_count = security_count
            snapshot.source_row_count = source_row_count
            snapshot.total_amount = total_amount
            snapshot.total_vol = total_vol
            snapshot.points_json = points_json
            snapshot.build_status = "READY"
            snapshot.build_version = TURNOVER_SNAPSHOT_BUILD_VERSION
            snapshot.built_at = datetime.now(timezone.utc)
            snapshot.build_note = None

        return TurnoverSnapshotBuildItem(
            trade_date=trade_date,
            freq=freq,
            build_status="READY",
            latest_trade_time=latest_trade_time,
            security_count=security_count,
            source_row_count=source_row_count,
            points_count=len(points_json),
            total_amount=total_amount,
            total_vol=total_vol,
            build_note=None,
        )

    @staticmethod
    def _normalize_freqs(freqs: list[int] | None) -> list[int]:
        if not freqs:
            return list(TURNOVER_SNAPSHOT_ALLOWED_FREQS)
        normalized: list[int] = []
        seen: set[int] = set()
        for raw_value in freqs:
            if raw_value not in TURNOVER_SNAPSHOT_ALLOWED_FREQS:
                raise ValueError(f"unsupported freq={raw_value}, allowed={TURNOVER_SNAPSHOT_ALLOWED_FREQS}")
            if raw_value in seen:
                continue
            seen.add(raw_value)
            normalized.append(raw_value)
        return normalized
