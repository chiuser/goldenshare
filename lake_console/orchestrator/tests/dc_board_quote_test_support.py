from datetime import datetime, timezone

from orchestrator.defs.asset_guards.dc_board_quote_coverage import empty_quote_coverage
from orchestrator.defs.asset_guards.dc_board_source_probe import (
    DcBoardProdCompletionResult,
)
from orchestrator.defs.run_contracts.configs import DcBoardSourceFreezeConfig
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_HISTORY_START_DATE,
    DC_QUOTE_COVERAGE_POLICY_VERSION,
)


def prod_result(snapshot):
    return DcBoardProdCompletionResult(snapshot.trade_date, True, "ready", snapshot, 3, 1.0)


def source_proof(completion, source, asset_name="raw_tushare_dc_index"):
    observed = datetime.now(timezone.utc).isoformat()
    coverage = empty_quote_coverage(completion.trade_date)
    return DcBoardSourceFreezeConfig(policy_version=DC_QUOTE_COVERAGE_POLICY_VERSION,
        trade_date=completion.trade_date, target_asset=asset_name,
        prod_observed_at_second=observed, prod_fingerprint_second=completion.completion_fingerprint,
        source_observed_at_second=observed, source_fingerprint_second=source.snapshot.source_fingerprint,
        history_start=DC_DAILY_HISTORY_START_DATE, history_file_count=0,
        history_evidence_digest=coverage.evidence_digest, coverage_gap_count=0)
