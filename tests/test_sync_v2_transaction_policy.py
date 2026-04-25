from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.contracts import (
    FetchResult,
    NormalizedBatch,
    PlanUnit,
    RunRequest,
    TransactionSpec,
    ValidatedRunRequest,
    WriteResult,
)
from src.foundation.services.sync_v2.engine import SyncV2Engine
from src.foundation.services.sync_v2.errors import SyncV2Error
from src.foundation.services.sync_v2.registry import get_sync_v2_contract


def _validated() -> ValidatedRunRequest:
    return ValidatedRunRequest(
        request_id="req",
        dataset_key="daily",
        run_profile="range_rebuild",
        trigger_source="test",
        params={},
        source_key=None,
        trade_date=None,
        start_date=date(2026, 4, 23),
        end_date=date(2026, 4, 24),
        correlation_id="corr",
        rerun_id=None,
        execution_id=1,
        validated_at=datetime.now(timezone.utc),
    )


def _unit(unit_id: str) -> PlanUnit:
    return PlanUnit(
        unit_id=unit_id,
        dataset_key="daily",
        source_key="tushare",
        trade_date=date(2026, 4, 24),
        request_params={"trade_date": "20260424"},
    )


def _unit_commit_contract():
    return replace(
        get_sync_v2_contract("daily"),
        transaction_spec=TransactionSpec(
            commit_policy="unit",
            idempotent_write_required=True,
            write_volume_assessment="test unit boundary",
        ),
    )


def test_engine_commits_each_successful_unit(mocker) -> None:
    session = mocker.Mock()
    engine = SyncV2Engine(session)
    units = [_unit("u1"), _unit("u2")]
    engine.validator.validate = mocker.Mock(return_value=_validated())
    engine.planner.plan = mocker.Mock(return_value=units)
    engine.worker.fetch = mocker.Mock(return_value=FetchResult("u", 1, 0, 1, [{"ts_code": "000001.SZ"}]))
    engine.normalizer.normalize = mocker.Mock(return_value=NormalizedBatch("u", [{"ts_code": "000001.SZ"}], 0, {}))
    engine.normalizer.raise_if_all_rejected = mocker.Mock()
    engine.writer.write = mocker.Mock(return_value=WriteResult("u", 1, 1, 0, "target", "upsert"))
    mocker.patch("src.foundation.services.sync_v2.engine.to_runtime_contract", return_value=SimpleNamespace(strategy_fn=None))

    summary = engine.run(
        request=RunRequest("req", "daily", "range_rebuild", "test"),
        contract=_unit_commit_contract(),
        strict_contract=True,
    )

    assert session.commit.call_count == 2
    assert summary.rows_written == 2
    assert summary.rows_committed == 2


def test_engine_keeps_committed_units_when_later_unit_fails(mocker) -> None:
    session = mocker.Mock()
    engine = SyncV2Engine(session)
    units = [_unit("u1"), _unit("u2")]
    engine.validator.validate = mocker.Mock(return_value=_validated())
    engine.planner.plan = mocker.Mock(return_value=units)
    engine.worker.fetch = mocker.Mock(return_value=FetchResult("u", 1, 0, 1, [{"ts_code": "000001.SZ"}]))
    engine.normalizer.normalize = mocker.Mock(return_value=NormalizedBatch("u", [{"ts_code": "000001.SZ"}], 0, {}))
    engine.normalizer.raise_if_all_rejected = mocker.Mock()
    engine.writer.write = mocker.Mock(
        side_effect=[
            WriteResult("u1", 1, 1, 0, "target", "upsert"),
            RuntimeError("boom"),
        ]
    )
    mocker.patch("src.foundation.services.sync_v2.engine.to_runtime_contract", return_value=SimpleNamespace(strategy_fn=None))

    with pytest.raises(SyncV2Error):
        engine.run(
            request=RunRequest("req", "daily", "range_rebuild", "test"),
            contract=_unit_commit_contract(),
            strict_contract=True,
        )

    assert session.commit.call_count == 1
    assert session.rollback.call_count == 1
