"""Approved Raw-only additions must not change frozen Silver identities."""
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from stock_suspend_confirmed_test_support import consumer_duckdb_resource

from orchestrator.defs.assets import stk_mins
from orchestrator.defs.run_contracts.stk_mins_silver_policy import (
    SILVER_STK_MINS_FROZEN_CODES,
)

from .test_stk_mins_silver_m5b_contracts import (
    _full_one_minute_rows,
    _identity_row,
    _read_rows,
    _silver_row,
    _stock_lifecycle_row,
    _write_common_inputs,
    _write_raw,
    _write_silver_for_check,
)

DAY = "2014-06-03"
NORMAL = "600000.SH"


def inputs(root: Path, freq: int) -> None:
    codes = (*SILVER_STK_MINS_FROZEN_CODES, NORMAL)
    _write_common_inputs(
        root, DAY, identity_rows=[_identity_row(c) for c in codes],
        daily_codes=codes,
        lifecycle_rows=[_stock_lifecycle_row(c, list_status="D", delist_date="2026-04-27") for c in codes],
    )
    _write_raw(root, 1, DAY, [r for c in codes for r in _full_one_minute_rows(c, DAY)])
    if freq != 1:
        # Two frozen native inputs; the third has only complete 1m input.
        _write_raw(root, freq, DAY, [
            dict(_full_one_minute_rows(c, DAY)[0], freq=freq)
            for c in SILVER_STK_MINS_FROZEN_CODES[:2]
        ])


def check_all_frequencies_preserve_only_existing_history(tmp_path, freq, existing, staged):
    inputs(tmp_path, freq)
    before = []
    if existing:
        path = _write_silver_for_check(tmp_path, DAY, [
            _silver_row(c, freq=freq, open_=23, high=25, low=21, close=24,
                        vol=321, amount=7654) for c in SILVER_STK_MINS_FROZEN_CODES
        ], freq=freq)
        before = _read_rows(path)
        original_bytes = path.read_bytes()
    result = stk_mins.write_silver_stk_mins_partition(
        lake_root=tmp_path, duckdb=consumer_duckdb_resource(), freq=freq,
        partition_key=DAY, overwrite=existing,
        output_path_override=tmp_path / "candidate.parquet" if staged else None,
    )
    rows = _read_rows(result.silver_file_path)
    assert [r for r in rows if r["ts_code"] in SILVER_STK_MINS_FROZEN_CODES] == before
    # A delisted identity outside the approved list must still be computed.
    assert any(r["ts_code"] == NORMAL for r in rows)
    assert result.materialization_extra_metadata(partition_key=DAY, freq=freq)["silver_freeze_policy_version"] == "2026-09-12"
    assert result.frozen_preserved_row_count == len(before)
    assert result.frozen_source_row_count == (723 if freq == 1 else 2)
    assert result.frozen_one_minute_source_row_count == (0 if freq == 1 else 723)
    if staged and existing:
        assert path.read_bytes() == original_bytes


def check_canonical_identity_filter(tmp_path):
    inputs(tmp_path, 1)
    alias = "000001.SZ"
    _write_common_inputs(tmp_path, DAY, identity_rows=[
        _identity_row(SILVER_STK_MINS_FROZEN_CODES[0], source_ts_code=alias),
        _identity_row("601360.SH", source_ts_code="601313.SH"),
    ], daily_codes=(SILVER_STK_MINS_FROZEN_CODES[0], "601360.SH"))
    _write_raw(tmp_path, 1, DAY,
               _full_one_minute_rows(alias, DAY) + _full_one_minute_rows("601313.SH", DAY))
    result = stk_mins.write_silver_stk_mins_partition(
        lake_root=tmp_path, duckdb=consumer_duckdb_resource(), freq=1, partition_key=DAY)
    assert {r["ts_code"] for r in _read_rows(result.silver_file_path)} == {"601360.SH"}


def check_duplicate_old_history_fails_without_modifying_file(tmp_path):
    inputs(tmp_path, 1)
    row = _silver_row(SILVER_STK_MINS_FROZEN_CODES[0])
    path = _write_silver_for_check(tmp_path, DAY, [row, row])
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="Frozen Silver history has duplicate keys"):
        stk_mins.write_silver_stk_mins_partition(
            lake_root=tmp_path, duckdb=consumer_duckdb_resource(), freq=1,
            partition_key=DAY, overwrite=True)
    assert path.read_bytes() == before


def check_exact_approved_scope():
    assert set(SILVER_STK_MINS_FROZEN_CODES) == {"600355.SH", "300344.SZ", "300391.SZ"}


class TestSilverFreezePolicy:
    def test_five_frequencies(self):
        for freq in (1, 5, 15, 30, 60):
            for existing in (False, True):
                for staged in (False, True):
                    with TemporaryDirectory() as directory:
                        check_all_frequencies_preserve_only_existing_history(
                            Path(directory), freq, existing, staged)

    def test_identity(self):
        with TemporaryDirectory() as directory:
            check_canonical_identity_filter(Path(directory))

    def test_duplicate(self):
        with TemporaryDirectory() as directory:
            check_duplicate_old_history_fails_without_modifying_file(Path(directory))

    def test_scope(self):
        check_exact_approved_scope()
