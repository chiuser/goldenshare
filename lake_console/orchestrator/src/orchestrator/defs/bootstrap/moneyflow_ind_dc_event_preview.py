"""Read-only moneyflow_ind_dc historical preview bound to its frozen dataset proof."""

from orchestrator.defs.bootstrap.moneyflow_history_event_preview import (
    moneyflow_history_proof,
    preview_moneyflow_history,
    read_moneyflow_event_state,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    BOARD_DC_MONEYFLOW_AUTOMATION,
)


def board_moneyflow_dc_history_proof(
    *,
    staging_root,
    lake_root,
    operation_id,
    cutoff,
    expected_cohort_hash,
    check=lambda: None,
):
    return moneyflow_history_proof(
        staging_root=staging_root,
        lake_root=lake_root,
        operation_id=operation_id,
        cutoff=cutoff,
        expected_cohort_hash=expected_cohort_hash,
        check=check,
        contract=BOARD_DC_MONEYFLOW_AUTOMATION,
    )


def read_board_moneyflow_dc_event_state(
    instance, entries, recent_dates, *, before_read=lambda: None
):
    return read_moneyflow_event_state(
        instance,
        entries,
        recent_dates,
        before_read=before_read,
        contract=BOARD_DC_MONEYFLOW_AUTOMATION,
    )


def preview_board_moneyflow_dc_history(
    *, instance, staging_root, lake_root, operation_id, cutoff, expected_cohort_hash
):
    return preview_moneyflow_history(
        instance=instance,
        staging_root=staging_root,
        lake_root=lake_root,
        operation_id=operation_id,
        cutoff=cutoff,
        expected_cohort_hash=expected_cohort_hash,
        contract=BOARD_DC_MONEYFLOW_AUTOMATION,
    )
