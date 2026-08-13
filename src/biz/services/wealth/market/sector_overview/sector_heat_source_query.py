from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.board_moneyflow_dc import BoardMoneyflowDc
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.equity_limit_list import EquityLimitList
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving.wealth_sector_heat_daily import WealthSectorHeatDaily

from .sector_heat_config import ResolvedSectorHeatConfig, canonical_json_hash
from .sector_heat_contract import PriorPublishedHeat


BOARD_MONEYFLOW_CONCEPT_CONTENT_TYPE = "概念"


class SectorHeatSourceNotReadyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SourceCompletionEvidence:
    dataset_key: str
    trade_date: date
    status: str
    evidence_type: str
    evidence_id: str
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class SectorIndexSourceRow:
    trade_date: date
    sector_code: str
    sector_name: str | None


@dataclass(frozen=True, slots=True)
class SectorDailySourceRow:
    trade_date: date
    sector_code: str
    pct_change: Decimal | None
    amount: Decimal | None


@dataclass(frozen=True, slots=True)
class SectorMemberSourceRow:
    trade_date: date
    sector_code: str
    stock_code: str


@dataclass(frozen=True, slots=True)
class SectorMoneyflowSourceRow:
    trade_date: date
    sector_code: str
    net_amount: Decimal | None
    net_amount_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class SecuritySourceRow:
    stock_code: str
    security_type: str
    curr_type: str | None
    list_status: str | None
    list_date: date | None
    delist_date: date | None


@dataclass(frozen=True, slots=True)
class EquityBarSourceRow:
    trade_date: date
    stock_code: str
    close: Decimal | None
    pct_chg: Decimal | None


@dataclass(frozen=True, slots=True)
class StockDateSourceRow:
    trade_date: date
    stock_code: str


@dataclass(frozen=True, slots=True)
class SectorHeatSourceBundle:
    target_date: date
    all_open_dates: tuple[date, ...]
    calculation_dates: tuple[date, ...]
    moneyflow_dates: tuple[date, ...]
    index_rows: tuple[SectorIndexSourceRow, ...]
    daily_rows: tuple[SectorDailySourceRow, ...]
    member_rows: tuple[SectorMemberSourceRow, ...]
    moneyflow_rows: tuple[SectorMoneyflowSourceRow, ...]
    security_rows: tuple[SecuritySourceRow, ...]
    bar_rows: tuple[EquityBarSourceRow, ...]
    limit_up_rows: tuple[StockDateSourceRow, ...]
    suspended_rows: tuple[StockDateSourceRow, ...]
    prior_published_by_date: Mapping[date, Mapping[str, PriorPublishedHeat]]
    source_dates_json: dict[str, object]
    source_row_counts_json: dict[str, object]
    source_hash: str
    completion_evidence: tuple[SourceCompletionEvidence, ...] = ()


class SectorHeatSourceQuery:
    def load(
        self,
        session: Session,
        *,
        trade_date: date,
        resolved_config: ResolvedSectorHeatConfig,
        completion_evidence: Sequence[SourceCompletionEvidence] = (),
        prior_published_override: Mapping[date, Mapping[str, PriorPublishedHeat]] | None = None,
    ) -> SectorHeatSourceBundle:
        config = resolved_config.payload
        required_open_days = config.baseline_trading_days + config.persistence_trading_days + 1
        open_dates_desc = tuple(
            session.scalars(
                select(TradeCalendar.trade_date)
                .where(
                    TradeCalendar.exchange == "SSE",
                    TradeCalendar.is_open.is_(True),
                    TradeCalendar.trade_date <= trade_date,
                )
                .order_by(TradeCalendar.trade_date.desc())
                .limit(required_open_days)
            )
        )
        if not open_dates_desc or open_dates_desc[0] != trade_date:
            raise SectorHeatSourceNotReadyError(f"target trade date is not an open SSE date: {trade_date.isoformat()}")
        if len(open_dates_desc) != required_open_days:
            raise SectorHeatSourceNotReadyError(
                f"trade calendar history insufficient: expected={required_open_days}, actual={len(open_dates_desc)}"
            )
        all_open_dates = tuple(reversed(open_dates_desc))
        calculation_dates = all_open_dates[-(config.persistence_trading_days + 1) :]
        moneyflow_dates = all_open_dates[-(config.persistence_trading_days + config.flow_trading_days) :]

        index_rows = tuple(
            SectorIndexSourceRow(row.trade_date, row.ts_code, row.name)
            for row in session.execute(
                select(DcIndex.trade_date, DcIndex.ts_code, DcIndex.name)
                .where(DcIndex.trade_date.in_(calculation_dates), DcIndex.idx_type == "概念板块")
                .order_by(DcIndex.trade_date, DcIndex.ts_code)
            )
        )
        self._require_dates("dc_index", index_rows, calculation_dates)
        self._assert_unique("dc_index", ((row.trade_date, row.sector_code) for row in index_rows))
        sector_codes = tuple(sorted({row.sector_code for row in index_rows}))

        daily_rows = tuple(
            SectorDailySourceRow(row.trade_date, row.ts_code, row.pct_change, row.amount)
            for row in session.execute(
                select(DcDaily.trade_date, DcDaily.ts_code, DcDaily.pct_change, DcDaily.amount)
                .where(
                    DcDaily.trade_date.in_(all_open_dates),
                    DcDaily.category == "概念板块",
                    DcDaily.ts_code.in_(sector_codes),
                )
                .order_by(DcDaily.trade_date, DcDaily.ts_code)
            )
        )
        self._require_dates("dc_daily", daily_rows, all_open_dates)
        self._assert_unique("dc_daily", ((row.trade_date, row.sector_code) for row in daily_rows))

        member_rows = tuple(
            SectorMemberSourceRow(row.trade_date, row.ts_code, row.con_code)
            for row in session.execute(
                select(DcMember.trade_date, DcMember.ts_code, DcMember.con_code)
                .where(DcMember.trade_date.in_(calculation_dates), DcMember.ts_code.in_(sector_codes))
                .order_by(DcMember.trade_date, DcMember.ts_code, DcMember.con_code)
            )
        )
        self._require_dates("dc_member", member_rows, calculation_dates)
        self._assert_unique(
            "dc_member", ((row.trade_date, row.sector_code, row.stock_code) for row in member_rows)
        )

        moneyflow_rows = tuple(
            SectorMoneyflowSourceRow(row.trade_date, row.ts_code, row.net_amount, row.net_amount_rate)
            for row in session.execute(
                select(
                    BoardMoneyflowDc.trade_date,
                    BoardMoneyflowDc.ts_code,
                    BoardMoneyflowDc.net_amount,
                    BoardMoneyflowDc.net_amount_rate,
                )
                .where(
                    BoardMoneyflowDc.trade_date.in_(moneyflow_dates),
                    BoardMoneyflowDc.content_type == BOARD_MONEYFLOW_CONCEPT_CONTENT_TYPE,
                    BoardMoneyflowDc.ts_code.is_not(None),
                    BoardMoneyflowDc.ts_code.in_(sector_codes),
                )
                .order_by(BoardMoneyflowDc.trade_date, BoardMoneyflowDc.ts_code)
            )
        )
        self._require_dates("board_moneyflow_dc", moneyflow_rows, moneyflow_dates)
        self._assert_unique(
            "board_moneyflow_dc", ((row.trade_date, row.sector_code) for row in moneyflow_rows)
        )

        stock_codes = tuple(sorted({row.stock_code for row in member_rows}))
        security_rows = tuple(
            SecuritySourceRow(
                row.ts_code,
                row.security_type,
                row.curr_type,
                row.list_status,
                row.list_date,
                row.delist_date,
            )
            for row in session.execute(
                select(
                    Security.ts_code,
                    Security.security_type,
                    Security.curr_type,
                    Security.list_status,
                    Security.list_date,
                    Security.delist_date,
                )
                .where(Security.ts_code.in_(stock_codes))
                .order_by(Security.ts_code)
            )
        )
        if stock_codes and not security_rows:
            raise SectorHeatSourceNotReadyError("security_serving has no rows for concept members")
        self._assert_unique("security_serving", ((row.stock_code,) for row in security_rows))

        bar_rows = tuple(
            EquityBarSourceRow(row.trade_date, row.ts_code, row.close, row.pct_chg)
            for row in session.execute(
                select(
                    EquityDailyBar.trade_date,
                    EquityDailyBar.ts_code,
                    EquityDailyBar.close,
                    EquityDailyBar.pct_chg,
                )
                .where(EquityDailyBar.trade_date.in_(calculation_dates), EquityDailyBar.ts_code.in_(stock_codes))
                .order_by(EquityDailyBar.trade_date, EquityDailyBar.ts_code)
            )
        )
        self._require_dates("equity_daily_bar", bar_rows, calculation_dates)
        self._assert_unique("equity_daily_bar", ((row.trade_date, row.stock_code) for row in bar_rows))

        limit_up_rows = tuple(
            StockDateSourceRow(row.trade_date, row.ts_code)
            for row in session.execute(
                select(EquityLimitList.trade_date, EquityLimitList.ts_code)
                .where(
                    EquityLimitList.trade_date.in_(calculation_dates),
                    EquityLimitList.ts_code.in_(stock_codes),
                    EquityLimitList.limit_type == "U",
                )
                .order_by(EquityLimitList.trade_date, EquityLimitList.ts_code)
            )
        )
        self._require_dates_or_evidence(
            "equity_limit_list", "limit_list_d", limit_up_rows, calculation_dates, completion_evidence
        )
        self._assert_unique("equity_limit_list", ((row.trade_date, row.stock_code) for row in limit_up_rows))

        suspended_rows = tuple(
            StockDateSourceRow(row.trade_date, row.ts_code)
            for row in session.execute(
                select(EquitySuspendD.trade_date, EquitySuspendD.ts_code)
                .where(
                    EquitySuspendD.trade_date.in_(calculation_dates),
                    EquitySuspendD.ts_code.in_(stock_codes),
                    EquitySuspendD.suspend_type == "S",
                )
                .distinct()
                .order_by(EquitySuspendD.trade_date, EquitySuspendD.ts_code)
            )
        )
        self._require_dates_or_evidence(
            "equity_suspend_d", "suspend_d", suspended_rows, calculation_dates, completion_evidence
        )
        self._assert_unique("equity_suspend_d", ((row.trade_date, row.stock_code) for row in suspended_rows))

        used_completion_evidence = self._used_completion_evidence(
            completion_evidence=completion_evidence,
            calculation_dates=calculation_dates,
            limit_up_rows=limit_up_rows,
            suspended_rows=suspended_rows,
        )

        previous_dates = calculation_dates[-max(config.trend_confirmation_days, 2) : -1]
        override_dates = {
            prior_date
            for prior_date in (prior_published_override or {})
            if prior_date in previous_dates
        }
        database_dates = tuple(item for item in previous_dates if item not in override_dates)
        prior_rows = tuple(
            session.execute(
                select(
                    WealthSectorHeatDaily.trade_date,
                    WealthSectorHeatDaily.sector_code,
                    WealthSectorHeatDaily.heat_status,
                    WealthSectorHeatDaily.heat_score,
                    WealthSectorHeatDaily.raw_heat_trend,
                    WealthSectorHeatDaily.score_version,
                    WealthSectorHeatDaily.config_hash,
                )
                .where(
                    WealthSectorHeatDaily.trade_date.in_(database_dates),
                    WealthSectorHeatDaily.sector_code.in_(sector_codes),
                )
                .order_by(WealthSectorHeatDaily.trade_date, WealthSectorHeatDaily.sector_code)
            )
        ) if database_dates else ()
        prior_published: dict[date, dict[str, PriorPublishedHeat]] = {}
        for row in prior_rows:
            prior_published.setdefault(row.trade_date, {})[row.sector_code] = PriorPublishedHeat(
                trade_date=row.trade_date,
                heat_status=row.heat_status,
                heat_score=row.heat_score,
                raw_heat_trend=row.raw_heat_trend,
                score_version=row.score_version,
                config_hash=row.config_hash,
            )
        for prior_date, rows in sorted((prior_published_override or {}).items()):
            if prior_date not in previous_dates:
                continue
            prior_published[prior_date] = {
                sector_code: row
                for sector_code, row in sorted(rows.items())
                if sector_code in sector_codes
            }
        prior_heat_canonical = [
            [
                prior_date.isoformat(),
                sector_code,
                row.heat_status,
                format(row.heat_score.normalize(), "f") if row.heat_score is not None else None,
                row.raw_heat_trend,
                row.score_version,
                row.config_hash,
            ]
            for prior_date, rows in sorted(prior_published.items())
            for sector_code, row in sorted(rows.items())
        ]

        row_counts: dict[str, object] = {
            "trade_calendar": len(all_open_dates),
            "dc_index": len(index_rows),
            "dc_daily": len(daily_rows),
            "dc_member": len(member_rows),
            "board_moneyflow_dc": len(moneyflow_rows),
            "security_serving": len(security_rows),
            "equity_daily_bar": len(bar_rows),
            "equity_limit_list": len(limit_up_rows),
            "equity_suspend_d": len(suspended_rows),
            "previous_heat": len(prior_heat_canonical),
        }
        source_dates: dict[str, object] = {
            "target": trade_date.isoformat(),
            "allOpenDates": [item.isoformat() for item in all_open_dates],
            "calculationDates": [item.isoformat() for item in calculation_dates],
            "moneyflowDates": [item.isoformat() for item in moneyflow_dates],
            "completionEvidence": [
                {
                    "datasetKey": item.dataset_key,
                    "tradeDate": item.trade_date.isoformat(),
                    "status": item.status,
                    "evidenceType": item.evidence_type,
                    "evidenceId": item.evidence_id,
                    "evidenceHash": item.evidence_hash,
                }
                for item in used_completion_evidence
            ],
        }
        source_hash = canonical_json_hash(
            {
                "queryBounds": source_dates,
                "dcIndex": self._canonical_rows(index_rows),
                "dcDaily": self._canonical_rows(daily_rows),
                "dcMember": self._canonical_rows(member_rows),
                "boardMoneyflowDc": self._canonical_rows(moneyflow_rows),
                "securityServing": self._canonical_rows(security_rows),
                "equityDailyBar": self._canonical_rows(bar_rows),
                "equityLimitList": self._canonical_rows(limit_up_rows),
                "equitySuspendD": self._canonical_rows(suspended_rows),
                "previousHeat": prior_heat_canonical,
                "completionEvidence": self._canonical_rows(
                    sorted(
                        used_completion_evidence,
                        key=lambda item: (
                            item.dataset_key,
                            item.trade_date,
                            item.status,
                            item.evidence_type,
                            item.evidence_id,
                            item.evidence_hash,
                        ),
                    )
                ),
            }
        )
        return SectorHeatSourceBundle(
            target_date=trade_date,
            all_open_dates=all_open_dates,
            calculation_dates=calculation_dates,
            moneyflow_dates=moneyflow_dates,
            index_rows=index_rows,
            daily_rows=daily_rows,
            member_rows=member_rows,
            moneyflow_rows=moneyflow_rows,
            security_rows=security_rows,
            bar_rows=bar_rows,
            limit_up_rows=limit_up_rows,
            suspended_rows=suspended_rows,
            prior_published_by_date=prior_published,
            source_dates_json=source_dates,
            source_row_counts_json=row_counts,
            source_hash=source_hash,
            completion_evidence=used_completion_evidence,
        )

    @staticmethod
    def _sector_codes_by_date(rows: Iterable[SectorIndexSourceRow]) -> dict[date, tuple[str, ...]]:
        grouped: dict[date, list[str]] = {}
        for row in rows:
            grouped.setdefault(row.trade_date, []).append(row.sector_code)
        return {trade_date: tuple(sorted(set(codes))) for trade_date, codes in grouped.items()}

    @staticmethod
    def _require_dates(source_name: str, rows: Sequence[Any], expected_dates: Sequence[date]) -> None:
        observed = {row.trade_date for row in rows}
        missing = [item.isoformat() for item in expected_dates if item not in observed]
        if missing:
            raise SectorHeatSourceNotReadyError(f"{source_name} missing whole source dates: {missing}")

    @staticmethod
    def _require_dates_or_evidence(
        source_name: str,
        dataset_key: str,
        rows: Sequence[Any],
        expected_dates: Sequence[date],
        evidence: Sequence[SourceCompletionEvidence],
    ) -> None:
        observed = {row.trade_date for row in rows}
        completed = {
            item.trade_date
            for item in evidence
            if item.dataset_key in {source_name, dataset_key} and item.status.upper() in {"SUCCESS", "COMPLETE"}
        }
        missing = [item.isoformat() for item in expected_dates if item not in observed and item not in completed]
        if missing:
            raise SectorHeatSourceNotReadyError(
                f"{source_name} zero rows without completion evidence: {missing}"
            )

    @staticmethod
    def _assert_unique(source_name: str, keys: Iterable[tuple[object, ...]]) -> None:
        counts = Counter(keys)
        duplicates = [key for key, count in counts.items() if count > 1]
        if duplicates:
            raise SectorHeatSourceNotReadyError(f"{source_name} semantic duplicate keys: {duplicates[:5]}")

    @staticmethod
    def _canonical_rows(rows: Iterable[Any]) -> list[list[object]]:
        canonical: list[list[object]] = []
        for row in rows:
            values = []
            for field_name in row.__dataclass_fields__:  # type: ignore[attr-defined]
                value = getattr(row, field_name)
                if isinstance(value, date):
                    value = value.isoformat()
                elif isinstance(value, Decimal):
                    value = format(value.normalize(), "f")
                values.append(value)
            canonical.append(values)
        return canonical

    @staticmethod
    def _used_completion_evidence(
        *,
        completion_evidence: Sequence[SourceCompletionEvidence],
        calculation_dates: Sequence[date],
        limit_up_rows: Sequence[StockDateSourceRow],
        suspended_rows: Sequence[StockDateSourceRow],
    ) -> tuple[SourceCompletionEvidence, ...]:
        observed_by_source = {
            "limit_list_d": {row.trade_date for row in limit_up_rows},
            "suspend_d": {row.trade_date for row in suspended_rows},
        }
        source_aliases = {
            "equity_limit_list": "limit_list_d",
            "limit_list_d": "limit_list_d",
            "equity_suspend_d": "suspend_d",
            "suspend_d": "suspend_d",
        }
        expected_dates = set(calculation_dates)
        selected = []
        for item in completion_evidence:
            normalized_key = source_aliases.get(item.dataset_key)
            if (
                normalized_key is not None
                and item.trade_date in expected_dates
                and item.trade_date not in observed_by_source[normalized_key]
                and item.status.upper() in {"SUCCESS", "COMPLETE"}
            ):
                selected.append(item)
        return tuple(
            sorted(
                selected,
                key=lambda item: (
                    item.dataset_key,
                    item.trade_date,
                    item.status,
                    item.evidence_type,
                    item.evidence_id,
                    item.evidence_hash,
                ),
            )
        )
