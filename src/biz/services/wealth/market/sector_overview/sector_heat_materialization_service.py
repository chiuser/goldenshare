from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from statistics import median
from typing import Mapping, Sequence

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.wealth_sector_heat_daily import WealthSectorHeatDaily

from .effective_a_stock_pool_query import EffectiveAStockPoolQuery, EffectiveAStockPoolSnapshot
from .sector_heat_config import SectorHeatConfigResolver, canonical_json_hash
from .sector_heat_contract import (
    PriorPublishedHeat,
    SectorHeatCandidate,
    SectorHeatContract,
    SectorHeatRawFeatureRow,
    SectorPoolCounts,
)
from .sector_heat_source_query import (
    SectorDailySourceRow,
    SectorHeatSourceBundle,
    SectorHeatSourceQuery,
    SectorIndexSourceRow,
    SectorMoneyflowSourceRow,
    SourceCompletionEvidence,
)


class SectorHeatMaterializationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SectorHeatMaterializationResult:
    trade_date: date
    rows_fetched: int
    rows_written: int
    valid_count: int
    invalid_count: int
    invalid_reason_counts: dict[str, int]
    config_version: str
    score_version: str
    config_hash: str
    source_hash: str
    plan_hash: str
    content_hash: str
    elapsed_ms: int
    source_dates: dict[str, object]
    source_row_counts: dict[str, object]
    skipped_existing: bool = False


@dataclass(frozen=True, slots=True)
class SectorHeatPreviewResult:
    trade_date: date
    rows_fetched: int
    rows_written: int
    valid_count: int
    invalid_count: int
    invalid_reason_counts: dict[str, int]
    config_version: str
    score_version: str
    config_hash: str
    source_hash: str
    plan_hash: str
    content_hash: str
    source_dates: dict[str, object]
    source_row_counts: dict[str, object]
    published_by_code: dict[str, PriorPublishedHeat]


@dataclass(frozen=True, slots=True)
class _PreparedSectorHeatDay:
    preview: SectorHeatPreviewResult
    table_rows: tuple[dict[str, object], ...]


class SectorHeatMaterializationService:
    def __init__(
        self,
        *,
        config_resolver: SectorHeatConfigResolver | None = None,
        source_query: SectorHeatSourceQuery | None = None,
        pool_query: EffectiveAStockPoolQuery | None = None,
    ) -> None:
        self._config_resolver = config_resolver or SectorHeatConfigResolver()
        self._source_query = source_query or SectorHeatSourceQuery()
        self._pool_query = pool_query or EffectiveAStockPoolQuery()

    def materialize_trade_date(
        self,
        session: Session,
        *,
        trade_date: date,
        expected_plan_hash: str | None = None,
        expected_content_hash: str | None = None,
        completion_evidence: Sequence[SourceCompletionEvidence] = (),
    ) -> SectorHeatMaterializationResult:
        started = time.perf_counter()
        try:
            prepared = self._prepare_trade_date(
                session=session,
                trade_date=trade_date,
                completion_evidence=completion_evidence,
            )
            preview = prepared.preview
            if expected_plan_hash is not None and expected_plan_hash != preview.plan_hash:
                raise SectorHeatMaterializationError(
                    "HEAT_PLAN_DRIFT: "
                    f"expected={expected_plan_hash}, actual={preview.plan_hash}, date={trade_date.isoformat()}"
                )
            if expected_content_hash is not None and expected_content_hash != preview.content_hash:
                raise SectorHeatMaterializationError(
                    "HEAT_CONTENT_DRIFT: "
                    f"expected={expected_content_hash}, actual={preview.content_hash}, date={trade_date.isoformat()}"
                )

            existing_rows = self._read_back(session, trade_date=trade_date)
            if (
                expected_content_hash is not None
                and len(existing_rows) == len(prepared.table_rows)
                and self._content_hash(existing_rows) == preview.content_hash
            ):
                return self._materialization_result(
                    preview=preview,
                    rows_written=0,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    skipped_existing=True,
                )

            session.execute(delete(WealthSectorHeatDaily).where(WealthSectorHeatDaily.trade_date == trade_date))
            if prepared.table_rows:
                session.execute(insert(WealthSectorHeatDaily), prepared.table_rows)
            session.flush()
            read_back = self._read_back(session, trade_date=trade_date)
            read_back_hash = self._content_hash(read_back)
            if len(read_back) != len(prepared.table_rows) or read_back_hash != preview.content_hash:
                raise SectorHeatMaterializationError(
                    "wealth sector heat read-back mismatch: "
                    f"expected_rows={len(prepared.table_rows)}, actual_rows={len(read_back)}, "
                    f"expected_hash={preview.content_hash}, actual_hash={read_back_hash}"
                )
            session.commit()
            return self._materialization_result(
                preview=preview,
                rows_written=preview.rows_written,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                skipped_existing=False,
            )
        except Exception:
            session.rollback()
            raise

    @staticmethod
    def _materialization_result(
        *,
        preview: SectorHeatPreviewResult,
        rows_written: int,
        elapsed_ms: int,
        skipped_existing: bool,
    ) -> SectorHeatMaterializationResult:
        return SectorHeatMaterializationResult(
            trade_date=preview.trade_date,
            rows_fetched=preview.rows_fetched,
            rows_written=rows_written,
            valid_count=preview.valid_count,
            invalid_count=preview.invalid_count,
            invalid_reason_counts=dict(preview.invalid_reason_counts),
            config_version=preview.config_version,
            score_version=preview.score_version,
            config_hash=preview.config_hash,
            source_hash=preview.source_hash,
            plan_hash=preview.plan_hash,
            content_hash=preview.content_hash,
            elapsed_ms=elapsed_ms,
            source_dates=dict(preview.source_dates),
            source_row_counts=dict(preview.source_row_counts),
            skipped_existing=skipped_existing,
        )

    def preview_trade_date(
        self,
        session: Session,
        *,
        trade_date: date,
        completion_evidence: Sequence[SourceCompletionEvidence] = (),
        prior_published_override: Mapping[date, Mapping[str, PriorPublishedHeat]] | None = None,
    ) -> SectorHeatPreviewResult:
        return self._prepare_trade_date(
            session=session,
            trade_date=trade_date,
            completion_evidence=completion_evidence,
            prior_published_override=prior_published_override,
        ).preview

    def _prepare_trade_date(
        self,
        *,
        session: Session,
        trade_date: date,
        completion_evidence: Sequence[SourceCompletionEvidence],
        prior_published_override: Mapping[date, Mapping[str, PriorPublishedHeat]] | None = None,
    ) -> _PreparedSectorHeatDay:
        resolved_config = self._config_resolver.resolve(market="CN_A")
        bundle = self._source_query.load(
            session,
            trade_date=trade_date,
            resolved_config=resolved_config,
            completion_evidence=completion_evidence,
            prior_published_override=prior_published_override,
        )
        sector_codes_by_date = self._sector_codes_by_date(bundle.index_rows)
        pools = self._pool_query.load(
            session,
            ordered_trade_dates=bundle.calculation_dates,
            sector_codes_by_date=sector_codes_by_date,
        )
        raw_rows_by_date = self._build_raw_features(
            bundle=bundle,
            pools=pools,
            config=resolved_config.payload,
        )
        candidates = SectorHeatContract(resolved_config.payload).calculate(
            ordered_trade_dates=bundle.calculation_dates,
            rows_by_date=raw_rows_by_date,
            prior_published_by_date=bundle.prior_published_by_date,
            config_hash=resolved_config.config_hash,
        )
        self._validate_candidates(bundle=bundle, candidates=candidates)
        plan_hash = canonical_json_hash(
            {
                "tradeDate": trade_date.isoformat(),
                "configVersion": resolved_config.version,
                "scoreVersion": resolved_config.payload.score_version,
                "configHash": resolved_config.config_hash,
                "sourceHash": bundle.source_hash,
            }
        )
        calculated_at = datetime.now(timezone.utc)
        table_rows = tuple(
            self._table_row(
                candidate=candidate,
                score_version=resolved_config.payload.score_version,
                config_hash=resolved_config.config_hash,
                source_hash=bundle.source_hash,
                source_dates=bundle.source_dates_json,
                source_row_counts=bundle.source_row_counts_json,
                calculated_at=calculated_at,
            )
            for candidate in candidates
        )
        content_hash = self._content_hash(table_rows)
        invalid_reason_counts = Counter(
            candidate.invalid_reason for candidate in candidates if candidate.invalid_reason is not None
        )
        published_by_code = {
            candidate.sector_code: self._prior_published(candidate, resolved_config.payload.score_version, resolved_config.config_hash)
            for candidate in candidates
        }
        return _PreparedSectorHeatDay(
            preview=SectorHeatPreviewResult(
                trade_date=trade_date,
                rows_fetched=sum(int(value) for value in bundle.source_row_counts_json.values()),
                rows_written=len(table_rows),
                valid_count=sum(candidate.heat_status == "VALID" for candidate in candidates),
                invalid_count=sum(candidate.heat_status == "INVALID" for candidate in candidates),
                invalid_reason_counts=dict(sorted(invalid_reason_counts.items())),
                config_version=resolved_config.version,
                score_version=resolved_config.payload.score_version,
                config_hash=resolved_config.config_hash,
                source_hash=bundle.source_hash,
                plan_hash=plan_hash,
                content_hash=content_hash,
                source_dates=dict(bundle.source_dates_json),
                source_row_counts=dict(bundle.source_row_counts_json),
                published_by_code=published_by_code,
            ),
            table_rows=table_rows,
        )

    @staticmethod
    def _prior_published(
        candidate: SectorHeatCandidate,
        score_version: str,
        config_hash: str,
    ) -> PriorPublishedHeat:
        return PriorPublishedHeat(
            trade_date=candidate.trade_date,
            heat_status=candidate.heat_status,
            heat_score=candidate.heat_score,
            raw_heat_trend=candidate.raw_heat_trend,
            score_version=score_version,
            config_hash=config_hash,
        )

    @staticmethod
    def _build_raw_features(
        *,
        bundle: SectorHeatSourceBundle,
        pools: Mapping[tuple[date, str], EffectiveAStockPoolSnapshot],
        config,  # type: ignore[no-untyped-def]
    ) -> dict[date, tuple[SectorHeatRawFeatureRow, ...]]:
        index_by_date: dict[date, dict[str, SectorIndexSourceRow]] = {}
        for row in bundle.index_rows:
            index_by_date.setdefault(row.trade_date, {})[row.sector_code] = row
        daily_by_key = {(row.trade_date, row.sector_code): row for row in bundle.daily_rows}
        moneyflow_by_key = {(row.trade_date, row.sector_code): row for row in bundle.moneyflow_rows}
        open_date_index = {trade_date: index for index, trade_date in enumerate(bundle.all_open_dates)}

        compounded_by_date: dict[date, dict[str, float]] = {}
        for calculation_date in bundle.calculation_dates:
            calculation_index = open_date_index[calculation_date]
            five_day_dates = bundle.all_open_dates[calculation_index - 4 : calculation_index + 1]
            values: dict[str, float] = {}
            if len(five_day_dates) == config.flow_trading_days:
                for sector_code in index_by_date.get(calculation_date, {}):
                    pct_changes = [
                        SectorHeatMaterializationService._decimal_float(
                            daily_by_key.get((historical_date, sector_code)).pct_change
                            if daily_by_key.get((historical_date, sector_code)) is not None
                            else None
                        )
                        for historical_date in five_day_dates
                    ]
                    if all(value is not None for value in pct_changes):
                        compounded = 1.0
                        for value in pct_changes:
                            assert value is not None
                            compounded *= 1 + value / 100
                        values[sector_code] = compounded - 1
            compounded_by_date[calculation_date] = values

        rows_by_date: dict[date, tuple[SectorHeatRawFeatureRow, ...]] = {}
        for calculation_date in bundle.calculation_dates:
            calculation_index = open_date_index[calculation_date]
            prior_date = bundle.all_open_dates[calculation_index - 1]
            five_day_dates = bundle.all_open_dates[calculation_index - config.flow_trading_days + 1 : calculation_index + 1]
            baseline_dates = bundle.all_open_dates[
                calculation_index - config.baseline_trading_days : calculation_index
            ]
            compounded_values = compounded_by_date[calculation_date]
            relative_median = median(compounded_values.values()) if compounded_values else None
            date_rows: list[SectorHeatRawFeatureRow] = []
            for sector_code, index_row in sorted(index_by_date.get(calculation_date, {}).items()):
                pool_snapshot = pools.get((calculation_date, sector_code))
                pool = pool_snapshot.counts if pool_snapshot is not None else SectorPoolCounts(0, 0, 0, 0, 0, 0, 0)
                invalid_reason = SectorHeatMaterializationService._pool_invalid_reason(pool=pool, config=config)
                current_daily = daily_by_key.get((calculation_date, sector_code))
                current_money = moneyflow_by_key.get((calculation_date, sector_code))
                current_pct = SectorHeatMaterializationService._daily_value(current_daily, "pct_change")
                current_amount = SectorHeatMaterializationService._daily_value(current_daily, "amount")
                current_net_amount = SectorHeatMaterializationService._money_value(current_money, "net_amount")
                current_net_rate = SectorHeatMaterializationService._money_value(current_money, "net_amount_rate")
                if invalid_reason is None and any(
                    value is None for value in (current_pct, current_amount, current_net_amount, current_net_rate)
                ):
                    invalid_reason = "FEATURE_MISSING"

                previous_pct = SectorHeatMaterializationService._daily_value(
                    daily_by_key.get((prior_date, sector_code)), "pct_change"
                )
                historical_amounts = [
                    SectorHeatMaterializationService._daily_value(
                        daily_by_key.get((historical_date, sector_code)), "amount"
                    )
                    for historical_date in baseline_dates
                ]
                historical_money = [moneyflow_by_key.get((historical_date, sector_code)) for historical_date in five_day_dates]
                historical_net_amounts = [
                    SectorHeatMaterializationService._money_value(row, "net_amount") for row in historical_money
                ]
                historical_net_rates = [
                    SectorHeatMaterializationService._money_value(row, "net_amount_rate") for row in historical_money
                ]
                compounded = compounded_values.get(sector_code)
                history_missing = (
                    previous_pct is None
                    or len(baseline_dates) != config.baseline_trading_days
                    or any(value is None for value in historical_amounts)
                    or len(five_day_dates) != config.flow_trading_days
                    or any(value is None for value in historical_net_amounts)
                    or any(value is None for value in historical_net_rates)
                    or compounded is None
                    or relative_median is None
                )
                if invalid_reason is None and history_missing:
                    invalid_reason = "HISTORY_INSUFFICIENT"

                baseline_median = (
                    median(value for value in historical_amounts if value is not None) if not history_missing else None
                )
                if invalid_reason is None and (baseline_median is None or baseline_median <= 0):
                    invalid_reason = "FEATURE_MISSING"

                up_ratio = (
                    pool_snapshot.up_count / pool.valid_quote_count
                    if pool_snapshot is not None and pool.valid_quote_count > 0
                    else None
                )
                limit_up_ratio = (
                    pool_snapshot.limit_up_count / pool.valid_quote_count
                    if pool_snapshot is not None and pool.valid_quote_count > 0
                    else None
                )
                date_rows.append(
                    SectorHeatRawFeatureRow(
                        trade_date=calculation_date,
                        sector_code=sector_code,
                        sector_name=index_row.sector_name or sector_code,
                        pool=pool,
                        invalid_reason=invalid_reason,
                        daily_return=current_pct,
                        relative_strength_5=(compounded - relative_median) if compounded is not None and relative_median is not None else None,
                        daily_acceleration=(current_pct - previous_pct) if current_pct is not None and previous_pct is not None else None,
                        up_ratio=up_ratio,
                        limit_up_ratio=limit_up_ratio,
                        net_inflow_strength=current_net_rate,
                        positive_inflow_day_ratio_5=(
                            sum(value > 0 for value in historical_net_amounts if value is not None)
                            / config.flow_trading_days
                            if not history_missing
                            else None
                        ),
                        net_inflow_rate_slope_5=(
                            SectorHeatContract.linear_slope(
                                [value for value in historical_net_rates if value is not None]
                            )
                            if not history_missing
                            else None
                        ),
                        activity=(current_amount / baseline_median) if current_amount is not None and baseline_median else None,
                    )
                )
            valid_compounded = {
                row.sector_code: compounded_values[row.sector_code]
                for row in date_rows
                if row.invalid_reason is None and row.sector_code in compounded_values
            }
            if valid_compounded:
                valid_relative_median = median(valid_compounded.values())
                date_rows = [
                    replace(
                        row,
                        relative_strength_5=(
                            compounded_values[row.sector_code] - valid_relative_median
                            if row.sector_code in valid_compounded
                            else row.relative_strength_5
                        ),
                    )
                    for row in date_rows
                ]
            rows_by_date[calculation_date] = tuple(date_rows)
        return rows_by_date

    @staticmethod
    def _pool_invalid_reason(*, pool: SectorPoolCounts, config) -> str | None:  # type: ignore[no-untyped-def]
        if pool.member_count < config.min_member_count:
            return "MEMBER_COUNT_LOW"
        if pool.quote_eligible_count == 0:
            return "QUOTE_ELIGIBLE_COUNT_ZERO"
        if Decimal(str(pool.quote_coverage)) < config.min_quote_coverage:
            return "QUOTE_COVERAGE_LOW"
        return None

    @staticmethod
    def _sector_codes_by_date(rows: Sequence[SectorIndexSourceRow]) -> dict[date, tuple[str, ...]]:
        grouped: dict[date, list[str]] = {}
        for row in rows:
            grouped.setdefault(row.trade_date, []).append(row.sector_code)
        return {trade_date: tuple(sorted(set(codes))) for trade_date, codes in grouped.items()}

    @staticmethod
    def _daily_value(row: SectorDailySourceRow | None, field_name: str) -> float | None:
        return SectorHeatMaterializationService._decimal_float(getattr(row, field_name) if row is not None else None)

    @staticmethod
    def _money_value(row: SectorMoneyflowSourceRow | None, field_name: str) -> float | None:
        return SectorHeatMaterializationService._decimal_float(getattr(row, field_name) if row is not None else None)

    @staticmethod
    def _decimal_float(value: Decimal | None) -> float | None:
        return float(value) if value is not None else None

    @staticmethod
    def _validate_candidates(*, bundle: SectorHeatSourceBundle, candidates) -> None:  # type: ignore[no-untyped-def]
        target_codes = {
            row.sector_code for row in bundle.index_rows if row.trade_date == bundle.target_date
        }
        candidate_codes = [row.sector_code for row in candidates]
        if len(candidate_codes) != len(set(candidate_codes)) or set(candidate_codes) != target_codes:
            raise SectorHeatMaterializationError(
                f"candidate identity mismatch: target={len(target_codes)}, candidates={len(candidate_codes)}"
            )
        valid_ranks = sorted(row.heat_rank for row in candidates if row.heat_rank is not None)
        if valid_ranks != list(range(1, len(valid_ranks) + 1)):
            raise SectorHeatMaterializationError("valid heat ranks are not unique and continuous")
        for row in candidates:
            pool = row.pool
            if pool.quote_eligible_count != pool.member_count - pool.suspended_count:
                raise SectorHeatMaterializationError(f"quote eligible count mismatch: {row.sector_code}")
            if pool.missing_quote_count != pool.quote_eligible_count - pool.valid_quote_count:
                raise SectorHeatMaterializationError(f"missing quote count mismatch: {row.sector_code}")

    @staticmethod
    def _table_row(
        *,
        candidate,  # type: ignore[no-untyped-def]
        score_version: str,
        config_hash: str,
        source_hash: str,
        source_dates: dict[str, object],
        source_row_counts: dict[str, object],
        calculated_at: datetime,
    ) -> dict[str, object]:
        pool = candidate.pool
        return {
            "trade_date": candidate.trade_date,
            "sector_code": candidate.sector_code,
            "sector_name": candidate.sector_name,
            "heat_status": candidate.heat_status,
            "invalid_reason": candidate.invalid_reason,
            "base_heat_score": candidate.base_heat_score,
            "base_heat_rank": candidate.base_heat_rank,
            "heat_score": candidate.heat_score,
            "heat_rank": candidate.heat_rank,
            "heat_level": candidate.heat_level,
            "heat_delta_1d": candidate.heat_delta_1d,
            "heat_trend": candidate.heat_trend,
            "raw_heat_trend": candidate.raw_heat_trend,
            "price_strength_score": candidate.price_strength_score,
            "breadth_score": candidate.breadth_score,
            "capital_flow_score": candidate.capital_flow_score,
            "activity_score": candidate.activity_score,
            "persistence_score": candidate.persistence_score,
            "source_member_count": pool.source_member_count,
            "member_count": pool.member_count,
            "suspended_count": pool.suspended_count,
            "quote_eligible_count": pool.quote_eligible_count,
            "valid_quote_count": pool.valid_quote_count,
            "missing_quote_count": pool.missing_quote_count,
            "quote_coverage": Decimal(str(pool.quote_coverage)).quantize(Decimal("0.000001")),
            "score_version": score_version,
            "config_hash": config_hash,
            "source_dates_json": dict(source_dates),
            "source_row_counts_json": dict(source_row_counts),
            "source_hash": source_hash,
            "calculated_at": calculated_at,
        }

    @staticmethod
    def _read_back(session: Session, *, trade_date: date) -> list[dict[str, object]]:
        columns = tuple(WealthSectorHeatDaily.__table__.columns)
        return [
            dict(row)
            for row in session.execute(
                select(*columns)
                .where(WealthSectorHeatDaily.trade_date == trade_date)
                .order_by(WealthSectorHeatDaily.sector_code)
            ).mappings()
        ]

    @staticmethod
    def _content_hash(rows: Sequence[Mapping[str, object]]) -> str:
        semantic_rows = [
            {key: value for key, value in sorted(row.items()) if key != "calculated_at"}
            for row in sorted(rows, key=lambda item: (item["trade_date"], item["sector_code"]))
        ]
        return canonical_json_hash(semantic_rows)
