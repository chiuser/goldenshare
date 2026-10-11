"""Complete source observations and shared, fail-closed quote coverage proof."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, sleep
from zoneinfo import ZoneInfo

from orchestrator.defs.asset_guards.dc_board_quote_coverage import (
    BoardQuoteCoverageResult,
    batch_board_quote_coverage,
)
from orchestrator.defs.asset_guards.dc_board_source_probe import (
    DcBoardProdCompletionResult,
    DcBoardSourceValidationError,
    DcBoardTushareSourceResult,
    build_dc_board_request_policy,
    load_prod_dc_board_reference_snapshot,
    load_tushare_dc_index_daily_source_snapshot,
)
from orchestrator.defs.run_contracts.configs import (
    DcBoardSourceFreezeConfig,
    validate_dc_board_source_freeze_config,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_CONFIRMATION_POLL_SECONDS,
    DC_BOARD_CURRENT_DAY_REFERENCE_NOT_BEFORE,
    DC_BOARD_OFFLINE_CONFIRMATION_SECONDS,
    DC_BOARD_REFERENCE_STABILITY_SECONDS,
    DC_BOARD_SOURCE_OBSERVATION_MAX_REQUESTS,
    DC_DAILY_HISTORY_START_DATE,
    DC_QUOTE_COVERAGE_POLICY_VERSION,
)
from orchestrator.defs.run_contracts.dc_board_failures import DcBoardRequestFailure


@dataclass(frozen=True, slots=True)
class DcBoardSourceObservation:
    prod: DcBoardProdCompletionResult
    source: DcBoardTushareSourceResult
    coverage: BoardQuoteCoverageResult
    prod_observed_at: str
    source_observed_at: str

    def checkpoint(self, asset_name: str) -> dict[str, object]:
        return {
            "policy_version": DC_QUOTE_COVERAGE_POLICY_VERSION,
            "target_asset": asset_name,
            "trade_date": self.coverage.target_date,
            "prod_observed_at": self.prod_observed_at,
            "prod_fingerprint": self.prod.snapshot.completion_fingerprint,
            "source_observed_at": self.source_observed_at,
            "source_fingerprint": self.source.snapshot.source_fingerprint,
            "history_digest": self.coverage.evidence_digest,
            "gap_count": self.coverage.gap_count,
        }


def observe_dc_board_source(
    *, lake_root: Path, duckdb_resource, prod_postgres, tushare, trade_date: str,
    policy=None, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> DcBoardSourceObservation:
    prod = load_prod_dc_board_reference_snapshot(prod_postgres=prod_postgres, trade_date=trade_date)
    prod_at = now().astimezone(timezone.utc).isoformat()
    if not prod.ready or prod.snapshot is None:
        raise DcBoardSourceValidationError(f"Prod reference unavailable: {prod.to_summary()}")
    base_policy = policy or build_dc_board_request_policy()
    bounded = replace(base_policy, max_requests=min(DC_BOARD_SOURCE_OBSERVATION_MAX_REQUESTS, base_policy.max_requests))
    source = load_tushare_dc_index_daily_source_snapshot(
        tushare=tushare, trade_date=trade_date, prod_completion=prod.snapshot, policy=bounded)
    source_at = now().astimezone(timezone.utc).isoformat()
    if not source.ready or source.snapshot is None:
        if source.failure_facts is not None:
            raise DcBoardRequestFailure(source.failure_facts)
        raise DcBoardSourceValidationError(f"Source snapshot unavailable: {source.to_summary()}")
    index_codes = {str(row["ts_code"]) for rows in source.index_rows_by_type.values() for row in rows}
    daily_codes = {str(row["ts_code"]) for row in source.daily_rows}
    coverage = batch_board_quote_coverage(lake_root=lake_root, duckdb_resource=duckdb_resource,
                                         gaps_by_date={trade_date: tuple(index_codes - daily_codes)})[trade_date]
    coverage = replace(coverage, index_count=len(index_codes), daily_count=len(daily_codes))
    if not coverage.ready:
        raise DcBoardSourceValidationError(f"Quote coverage blocked: {coverage.metadata()}")
    return DcBoardSourceObservation(prod, source, coverage, prod_at, source_at)


def confirm_dc_board_source(
    observation: DcBoardSourceObservation, *, asset_name: str,
    prior: Mapping[str, object] | None, now: datetime | None = None,
) -> DcBoardSourceFreezeConfig | None:
    """Return no proof until a compatible compact first observation has matured."""
    moment = now or datetime.now(timezone.utc)
    day = observation.coverage.target_date
    local = moment.astimezone(ZoneInfo("Asia/Shanghai"))
    current_index = asset_name == "raw_tushare_dc_index" and day == local.date().isoformat()
    if current_index and local.time() < DC_BOARD_CURRENT_DAY_REFERENCE_NOT_BEFORE:
        return None
    source_pair = observation.coverage.gap_count > 0 or (
        asset_name == "raw_tushare_dc_index" and not observation.source.content_matches_prod)
    current = observation.checkpoint(asset_name)
    matching = prior is not None and all(prior.get(key) == current[key] for key in (
        "policy_version", "target_asset", "trade_date", "history_digest", "gap_count"))
    if source_pair:
        matching = matching and prior.get("source_fingerprint") == current["source_fingerprint"]
    if current_index:
        matching = matching and prior.get("prod_fingerprint") == current["prod_fingerprint"]
    if source_pair or current_index:
        if not matching:
            return None
        roles = (("source",) if source_pair else ()) + (("prod",) if current_index else ())
        for role in roles:
            try:
                first = datetime.fromisoformat(str(prior[f"{role}_observed_at"]))
                second = datetime.fromisoformat(str(current[f"{role}_observed_at"]))
                if first.tzinfo is None or (second - first).total_seconds() < DC_BOARD_REFERENCE_STABILITY_SECONDS:
                    return None
            except (ValueError, KeyError, TypeError):
                return None
    proof = DcBoardSourceFreezeConfig(
        policy_version=DC_QUOTE_COVERAGE_POLICY_VERSION, trade_date=day, target_asset=asset_name,
        prod_observed_at_first=str(prior["prod_observed_at"]) if current_index else None,
        prod_fingerprint_first=str(prior["prod_fingerprint"]) if current_index else None,
        prod_observed_at_second=observation.prod_observed_at,
        prod_fingerprint_second=observation.prod.snapshot.completion_fingerprint,
        source_observed_at_first=str(prior["source_observed_at"]) if source_pair else None,
        source_fingerprint_first=str(prior["source_fingerprint"]) if source_pair else None,
        source_observed_at_second=observation.source_observed_at,
        source_fingerprint_second=observation.source.snapshot.source_fingerprint,
        history_start=DC_DAILY_HISTORY_START_DATE, history_end=observation.coverage.history_end,
        history_file_count=len(observation.coverage.file_signatures),
        history_evidence_digest=observation.coverage.evidence_digest,
        coverage_gap_count=observation.coverage.gap_count,
    )
    return validate_dc_board_source_freeze_config(proof, partition_key=day, asset_name=asset_name, now=moment)


def revalidate_dc_board_source(
    *, proof: DcBoardSourceFreezeConfig, asset_name: str, partition_key: str,
    lake_root: Path, duckdb_resource, prod_postgres, tushare, policy=None,
) -> DcBoardSourceObservation:
    validate_dc_board_source_freeze_config(proof, partition_key=partition_key, asset_name=asset_name)
    observation = observe_dc_board_source(lake_root=lake_root, duckdb_resource=duckdb_resource,
                                         prod_postgres=prod_postgres, tushare=tushare,
                                         trade_date=partition_key, policy=policy)
    if (observation.prod.snapshot.completion_fingerprint != proof.prod_fingerprint_second
            or observation.source.snapshot.source_fingerprint != proof.source_fingerprint_second
            or observation.coverage.evidence_digest != proof.history_evidence_digest
            or observation.coverage.gap_count != proof.coverage_gap_count
            or observation.coverage.history_end != proof.history_end
            or len(observation.coverage.file_signatures) != proof.history_file_count):
        raise DcBoardSourceValidationError("source/history changed after freeze; promotion blocked", reason_code="source_changed_after_freeze")
    if asset_name == "raw_tushare_dc_index" and not observation.source.content_matches_prod and proof.source_observed_at_first is None:
        raise DcBoardSourceValidationError("source/Prod difference requires stable source pair")
    return observation


def observe_and_confirm_dc_board_source(
    *, asset_name: str, lake_root: Path, duckdb_resource, prod_postgres, tushare,
    trade_date: str, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    wait: Callable[[float], None] = sleep, clock: Callable[[], float] = monotonic,
    progress: Callable[[str], None] = print,
) -> DcBoardSourceFreezeConfig:
    """Bounded offline confirmation; completed dates remain independent units."""
    deadline = clock() + DC_BOARD_OFFLINE_CONFIRMATION_SECONDS
    prior = None
    while clock() < deadline:
        observation = observe_dc_board_source(lake_root=lake_root, duckdb_resource=duckdb_resource,
                                             prod_postgres=prod_postgres, tushare=tushare,
                                             trade_date=trade_date, now=now)
        proof = confirm_dc_board_source(observation, asset_name=asset_name, prior=prior, now=now())
        if clock() >= deadline:
            break
        if proof is not None:
            return proof
        candidate = observation.checkpoint(asset_name)
        keys = ["policy_version", "target_asset", "trade_date", "source_fingerprint", "history_digest", "gap_count"]
        if asset_name == "raw_tushare_dc_index" and trade_date == now().astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat():
            keys.append("prod_fingerprint")
        if prior is None or any(prior.get(k) != candidate[k] for k in keys):
            prior = candidate
        progress(f"{trade_date}: waiting for stable source confirmation")
        # Do not refetch a complete snapshot every 5s; only poll cancellation/progress.
        observed = datetime.fromisoformat(str(prior["source_observed_at"]))
        while (now() - observed).total_seconds() < DC_BOARD_REFERENCE_STABILITY_SECONDS and clock() < deadline:
            wait(min(DC_BOARD_CONFIRMATION_POLL_SECONDS, deadline - clock()))
            progress(f"{trade_date}: source confirmation pending")
    raise DcBoardSourceValidationError("source confirmation deadline exceeded")
