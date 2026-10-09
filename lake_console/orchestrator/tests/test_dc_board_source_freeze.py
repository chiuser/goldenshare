from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.defs.asset_guards import dc_board_source_freeze as freeze
from orchestrator.defs.asset_guards.dc_board_quote_coverage import (
    AWAITING_QUOTE,
    BoardQuoteCoverageResult,
    BoardQuoteEvidence,
    empty_quote_coverage,
)
from orchestrator.defs.run_contracts.configs import (
    validate_dc_board_source_freeze_config,
)
from tests.dc_board_quote_test_support import prod_result, source_proof
from tests.test_dc_board_raw_io import _completion, _source_result

DAY = "2026-07-14"
START = datetime(2026, 7, 14, 13, 16, tzinfo=timezone.utc)


def observation(moment=START, *, gap=False, source=None, prod=None):
    coverage = (BoardQuoteCoverageResult(DAY, (BoardQuoteEvidence("BK1754.DC", AWAITING_QUOTE),),
                                        "2026-07-13", True) if gap else empty_quote_coverage(DAY))
    return freeze.DcBoardSourceObservation(prod_result(prod or _completion()), source or _source_result(),
                                          coverage, moment.isoformat(), moment.isoformat())


def test_gap_requires_complete_pair_and_300_seconds():
    first = observation(gap=True)
    assert freeze.confirm_dc_board_source(first, asset_name="raw_tushare_dc_daily", prior=None, now=START) is None
    prior = first.checkpoint("raw_tushare_dc_daily")
    for seconds in (0, 299):
        now = START + timedelta(seconds=seconds)
        assert freeze.confirm_dc_board_source(observation(now, gap=True), asset_name="raw_tushare_dc_daily", prior=prior, now=now) is None
    now = START + timedelta(seconds=300)
    proof = freeze.confirm_dc_board_source(observation(now, gap=True), asset_name="raw_tushare_dc_daily", prior=prior, now=now)
    assert proof.coverage_gap_count == 1
    assert proof.prod_observed_at_first is None
    assert proof.source_observed_at_first == START.isoformat()


def test_no_gap_downstream_has_no_extra_stability_wait():
    for asset in ("raw_tushare_dc_daily", "raw_tushare_dc_member"):
        proof = freeze.confirm_dc_board_source(observation(), asset_name=asset, prior=None, now=START)
        assert proof and proof.source_observed_at_first is None and proof.prod_observed_at_first is None


def test_current_index_requires_window_and_prod_pair():
    early = START.replace(hour=13, minute=14)
    assert freeze.confirm_dc_board_source(observation(early), asset_name="raw_tushare_dc_index", prior=None, now=early) is None
    first = observation()
    prior = first.checkpoint("raw_tushare_dc_index")
    now = START + timedelta(seconds=300)
    proof = freeze.confirm_dc_board_source(observation(now), asset_name="raw_tushare_dc_index", prior=prior, now=now)
    assert proof and proof.prod_observed_at_first == START.isoformat()
    changed = replace(observation(now), prod=prod_result(_completion(("BK0004.DC", "BK0005.DC", "BK0006.DC"))))
    assert freeze.confirm_dc_board_source(changed, asset_name="raw_tushare_dc_index", prior=prior, now=now) is None


@pytest.mark.parametrize("changed", ["source", "history", "policy", "asset"])
def test_confirmation_rejects_changed_or_retired_checkpoint(changed):
    first = observation(gap=True)
    prior = first.checkpoint("raw_tushare_dc_daily")
    prior[{"source": "source_fingerprint", "history": "history_digest", "policy": "policy_version", "asset": "target_asset"}[changed]] = "changed"
    now = START + timedelta(seconds=600)
    assert freeze.confirm_dc_board_source(observation(now, gap=True), asset_name="raw_tushare_dc_daily", prior=prior, now=now) is None


@pytest.mark.parametrize("field,value", [
    ("policy_version", "retired"), ("trade_date", "2026-07-15"),
    ("target_asset", "raw_tushare_dc_member"), ("history_start", "2026-01-01"),
    ("history_end", DAY), ("history_file_count", -1), ("coverage_gap_count", -1),
    ("coverage_gap_count", 1), ("history_evidence_digest", "invalid"),
    ("source_observed_at_second", "2026-07-14T13:16:00"),
    ("source_observed_at_second", "2026-07-14T21:16:00+08:00"),
    ("source_observed_at_second", "2099-01-01T00:00:00+00:00"),
    ("source_observed_at_first", START.isoformat()),
])
def test_run_config_rejects_invalid_proof(field, value):
    proof = source_proof(_completion(), _source_result())
    proof = proof.model_copy(update={field: value})
    with pytest.raises(ValueError):
        validate_dc_board_source_freeze_config(proof, partition_key=DAY, asset_name="raw_tushare_dc_index")


def test_writer_revalidation_refuses_fingerprint_or_history_drift(monkeypatch, tmp_path):
    frozen = observation(START - timedelta(days=1))
    proof = freeze.confirm_dc_board_source(frozen, asset_name="raw_tushare_dc_daily", prior=None, now=START)
    for changed in (replace(frozen, source=_source_result(close=11)),
                    replace(frozen, coverage=replace(frozen.coverage, calendar_dates=("2024-01-02",)))):
        monkeypatch.setattr(freeze, "observe_dc_board_source", lambda changed=changed, **_: changed)
        with pytest.raises(ValueError, match="changed after freeze"):
            freeze.revalidate_dc_board_source(proof=proof, asset_name="raw_tushare_dc_daily", partition_key=DAY,
                lake_root=tmp_path, duckdb_resource=object(), prod_postgres=object(), tushare=object())


def test_offline_confirmation_is_bounded_and_polls_without_refetch(monkeypatch, tmp_path):
    seconds = [0.0]
    calls = []
    def observe(**_):
        calls.append(seconds[0])
        return observation(START + timedelta(seconds=seconds[0]), gap=True)
    monkeypatch.setattr(freeze, "observe_dc_board_source", observe)
    proof = freeze.observe_and_confirm_dc_board_source(asset_name="raw_tushare_dc_daily", lake_root=tmp_path,
        duckdb_resource=object(), prod_postgres=object(), tushare=object(),
        trade_date=DAY, now=lambda: START + timedelta(seconds=seconds[0]),
        clock=lambda: seconds[0], wait=lambda n: seconds.__setitem__(0, seconds[0] + n), progress=lambda _: None)
    assert proof and calls == [0, 300]


def test_offline_confirmation_times_out_without_unbounded_retries(monkeypatch, tmp_path):
    seconds = [0.0]
    def observe(**_):
        return observation(START + timedelta(seconds=seconds[0]), gap=True,
                           source=_source_result(close=10 + seconds[0]))
    monkeypatch.setattr(freeze, "observe_dc_board_source", observe)
    with pytest.raises(ValueError, match="deadline exceeded"):
        freeze.observe_and_confirm_dc_board_source(asset_name="raw_tushare_dc_daily", lake_root=tmp_path,
            duckdb_resource=object(), prod_postgres=object(), tushare=object(), trade_date=DAY,
            now=lambda: START + timedelta(seconds=seconds[0]), clock=lambda: seconds[0],
            wait=lambda n: seconds.__setitem__(0, seconds[0] + n), progress=lambda _: None)
    assert seconds[0] == 600
