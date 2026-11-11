"""Remove downloaded THS stock pages only after the complete Raw run succeeds."""

import re
from pathlib import Path

import dagster as dg

from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_directory
from orchestrator.defs.io.moneyflow_update_publication import (
    assert_moneyflow_update_path,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_REQUESTS,
    MONEYFLOW_THS_RAW_CHECK,
    MoneyflowContractError,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    STOCK_THS_MONEYFLOW_AUTOMATION,
)


def cleanup_moneyflow_ths_pages(
    *, staging_root: Path, run: dg.DagsterRun, raw_check
) -> tuple[int, int]:
    """Keep failed runs and recovery files; repeated cleanup removes no new data."""
    day = run.tags.get("dagster/partition")
    if (
        run.job_name != STOCK_THS_MONEYFLOW_AUTOMATION.raw_job
        or run.status != dg.DagsterRunStatus.SUCCESS
        or not day
        or raw_check is None
        or not raw_check.passed
        or raw_check.asset_key != dg.AssetKey("raw_tushare_moneyflow_ths")
        or raw_check.check_name != MONEYFLOW_THS_RAW_CHECK
    ):
        return 0, 0

    directory = moneyflow_candidate_directory(
        staging_root, run.run_id, day, dataset="moneyflow_ths"
    )
    pages = []
    for number in (1, 2):
        scope = directory / f"round-{number}" / "scope-1"
        assert_moneyflow_update_path(scope)
        for page in scope.glob("page-*.json"):
            if re.fullmatch(r"page-[0-9]+\.json", page.name) is None:
                continue
            assert_moneyflow_update_path(page)
            if not page.is_file():
                raise MoneyflowContractError("source_page_not_file")
            pages.append(page)
            if len(pages) > MONEYFLOW_MAX_REQUESTS:
                raise MoneyflowContractError("source_page_count")

    deleted_bytes = 0
    for page in pages:
        size = page.stat().st_size
        page.unlink()
        deleted_bytes += size
    return len(pages), deleted_bytes
