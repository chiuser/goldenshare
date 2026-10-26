"""Literal LLD 17.8.2 budgets; no database, volume or production IO."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as R


def estimate(**changes):
    args = {
        "pending_source_rows_by_month": (),
        "remaining_layer_rows": (),
        "work_rows": (0, 0),
        "pending_fetch_rows": 0,
        "remaining_date_count": 0,
    }
    args.update(changes)
    return R.estimate_bootstrap_space(**args)


def require(tmp_path, value, **changes):
    args = {
        "estimate": value,
        "operation_id": "bootstrap-test",
        "stage": "保存前",
        "staging_root": tmp_path / "staging" / "not-created",
        "temp_directory": tmp_path / "duckdb" / "not-created",
    }
    args.update(changes)
    return R.require_bootstrap_space(**args)


def test_monthly_fragments_cumulative_layers_and_work_have_literal_bytes():
    # Independent arithmetic: P(5000)=25,084,304, P(1)=4,198,482,
    # P(3)=4,206,838 and P(5)=4,215,194 bytes (2*2089*n+4MiB).
    actual = estimate(
        pending_source_rows_by_month=(5001, 1),
        remaining_layer_rows=(3, 3),
        work_rows=(3, 3),
        pending_fetch_rows=5,
        remaining_date_count=2,
    )
    assert actual == R.BootstrapSpaceEstimate(
        source_bytes=33_481_268,
        candidate_bytes=8_413_676,
        temp_bytes=50_515_480,
        record_bytes=3_145_728,
    )
    with pytest.raises(FrozenInstanceError):
        actual.source_bytes = 0


def test_ten_days_need_all_twenty_new_files_not_one_day():
    actual = estimate(
        pending_source_rows_by_month=(10,),
        remaining_layer_rows=(1,) * 20,
        work_rows=(1, 1),
        pending_fetch_rows=10,
        remaining_date_count=10,
    )
    assert actual.source_bytes == 4_236_084
    assert actual.candidate_bytes == 83_969_640
    assert actual.temp_bytes == 50_532_192
    assert actual.record_bytes == 11_534_336


def test_reused_source_and_files_do_not_remove_calculation_space():
    actual = estimate(work_rows=(3, 3), remaining_date_count=1)
    assert actual.source_bytes == actual.candidate_bytes == 0
    assert actual.temp_bytes == 33_654_704
    assert actual.record_bytes == 2_097_152


def test_statistics_original_zero_current_five_uses_current_work():
    actual = estimate(statistics_only=True, work_rows=(5, 5), remaining_date_count=1)
    assert actual.source_bytes == actual.candidate_bytes == 0
    assert actual.temp_bytes == 16_860_776
    assert actual.record_bytes == 2_097_152


def test_empty_work_still_reserves_final_summary():
    assert estimate() == R.BootstrapSpaceEstimate(0, 0, 0, 1_048_576)


def test_observed_sizes_can_only_raise_the_initial_estimate():
    actual = estimate(
        pending_source_rows_by_month=(1,),
        remaining_layer_rows=(1, 1),
        work_rows=(1, 1),
        pending_fetch_rows=1,
        remaining_date_count=2,
        observed_row_bytes=4179,
        observed_file_overhead=4_194_305,
        observed_record_bytes=1_048_577,
    )
    assert actual == R.BootstrapSpaceEstimate(
        4_198_484, 8_396_968, 50_381_808, 3_145_731
    )


def test_layer_totals_equal_literal_per_file_budget_without_counting_empty_files():
    # 9 rows across 3 nonempty files: 4178*9 + 4MiB*3 = 12,620,514.
    expected = R.BootstrapSpaceEstimate(0, 12_620_514, 0, 1_048_576)
    assert estimate(remaining_layer_rows=(1, 0, 3, 5, 0)) == expected
    assert estimate(remaining_layer_totals=(9, 3)) == expected


def test_large_layer_totals_do_not_require_a_per_file_list():
    # 10**12 rows and 10**8 nonempty files, represented by exactly two integers.
    actual = estimate(remaining_layer_totals=(1_000_000_000_000, 100_000_000))
    assert actual.candidate_bytes == 4_597_430_400_000_000


def test_layer_totals_use_observed_growth_and_zero_totals_allow_local_statistics():
    assert (
        estimate(
            remaining_layer_totals=(9, 3),
            observed_row_bytes=4179,
            observed_file_overhead=4_194_305,
        ).candidate_bytes
        == 12_620_526
    )
    assert estimate(
        remaining_layer_totals=(0, 0), statistics_only=True
    ) == R.BootstrapSpaceEstimate(0, 0, 0, 1_048_576)


@pytest.mark.parametrize(
    "totals",
    [
        (1,),
        (1, 2, 3),
        [1, 1],
        (True, 1),
        (1, False),
        (-1, 1),
        (1, -1),
        (1.0, 1),
        (1, 1.0),
        (1, 0),
        (0, 1),
        (1, 2),
    ],
)
def test_layer_totals_require_real_counts_consistent_with_nonempty_files(totals):
    with pytest.raises(ValueError):
        estimate(remaining_layer_totals=totals)


def test_layer_totals_cannot_double_count_or_hide_nonlocal_work():
    with pytest.raises(ValueError, match="不能同时计入"):
        estimate(remaining_layer_rows=(1,), remaining_layer_totals=(1, 1))
    with pytest.raises(ValueError, match="不能同时计入"):
        estimate(remaining_layer_rows=(0,), remaining_layer_totals=(0, 0))
    with pytest.raises(ValueError, match="仅本地统计"):
        estimate(remaining_layer_totals=(1, 1), statistics_only=True)


@pytest.mark.parametrize(
    "change",
    [
        {"pending_source_rows_by_month": [1]},
        {"pending_source_rows_by_month": (True,)},
        {"remaining_layer_rows": (-1,)},
        {"remaining_layer_rows": (1.0,)},
        {"work_rows": (1,)},
        {"work_rows": (None, 1)},
        {"pending_fetch_rows": 5001},
        {"pending_fetch_rows": False},
        {"remaining_date_count": -1},
        {"statistics_only": 1},
        {"observed_row_bytes": 4177},
        {"observed_file_overhead": 4_194_303},
        {"observed_record_bytes": 1_048_575},
        {"statistics_only": True, "pending_source_rows_by_month": (1,)},
        {"statistics_only": True, "remaining_layer_rows": (1,)},
        {"statistics_only": True, "pending_fetch_rows": 1},
    ],
)
def test_illegal_or_conflicting_estimator_inputs_are_rejected(change):
    with pytest.raises(ValueError):
        estimate(**change)


@pytest.mark.parametrize("value", [-1, True, 1.5, None])
def test_estimate_carrier_rejects_non_integer_or_negative_bytes(value):
    with pytest.raises(ValueError):
        R.BootstrapSpaceEstimate(value, 0, 0, 0)


@pytest.mark.parametrize("extra", [0, 1, 4096])
def test_same_device_combines_all_requirements_and_reserves_once(
    tmp_path, monkeypatch, extra
):
    calls = []

    def disk_usage(path):
        calls.append(path)
        # 10+20+30+40 bytes + one 16MiB reserve, not two reserves.
        return SimpleNamespace(free=16_777_316 + extra)

    monkeypatch.setattr(R.shutil, "disk_usage", disk_usage)
    require(tmp_path, R.BootstrapSpaceEstimate(10, 20, 30, 40))
    assert calls == [tmp_path]
    assert not (tmp_path / "staging").exists()
    assert not (tmp_path / "duckdb").exists()


def test_same_device_cannot_pass_each_amount_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(
        R.shutil, "disk_usage", lambda _: SimpleNamespace(free=16_777_315)
    )
    with pytest.raises(ValueError, match="required=16777316，free=16777315"):
        require(tmp_path, R.BootstrapSpaceEstimate(10, 20, 30, 40))


def test_different_devices_must_each_have_space(tmp_path, monkeypatch):
    staging, temp = tmp_path / "staging", tmp_path / "duckdb"
    staging.mkdir()
    temp.mkdir()
    real_ancestor = R._bootstrap_space_ancestor
    calls = []

    def ancestor(path):
        found, _ = real_ancestor(path)
        return found, 100 if found == staging else 200

    def disk_usage(path):
        calls.append(path)
        return SimpleNamespace(free=1_000_000_000 if path == staging else 16_777_245)

    monkeypatch.setattr(R, "_bootstrap_space_ancestor", ancestor)
    monkeypatch.setattr(R.shutil, "disk_usage", disk_usage)
    with pytest.raises(ValueError, match="设备=200.*required=16777246"):
        require(
            tmp_path,
            R.BootstrapSpaceEstimate(10, 20, 30, 40),
            staging_root=staging,
            temp_directory=temp,
        )
    assert calls == [staging, temp]


def test_unused_temp_device_does_not_require_another_reserve(tmp_path, monkeypatch):
    calls = []

    def disk_usage(path):
        calls.append(path)
        return SimpleNamespace(free=17_825_792)

    monkeypatch.setattr(R.shutil, "disk_usage", disk_usage)
    require(tmp_path, estimate())
    assert calls == [tmp_path]


@pytest.mark.parametrize("failure", ["stat", "capacity"])
def test_cannot_read_device_or_capacity_fails_explicitly(
    tmp_path, monkeypatch, failure
):
    def broken(_):
        raise PermissionError("injected no access")

    if failure == "stat":
        monkeypatch.setattr(R, "_bootstrap_space_ancestor", broken)
    else:
        monkeypatch.setattr(R.shutil, "disk_usage", broken)
    with pytest.raises(ValueError, match="operation=bootstrap-test.*free=未知"):
        require(tmp_path, estimate())


@pytest.mark.parametrize("kind", ["relative", "parent", "symlink", "file"])
def test_safe_existing_ancestor_never_creates_or_follows_unsafe_path(tmp_path, kind):
    root = tmp_path / "root"
    root.mkdir()
    if kind == "relative":
        path = root.relative_to(root.anchor)
    elif kind == "parent":
        path = root / ".." / "outside"
    elif kind == "symlink":
        path = tmp_path / "link"
        path.symlink_to(root, target_is_directory=True)
    else:
        path = root / "data"
        path.write_bytes(b"file is not a directory")
    with pytest.raises((ValueError, NotADirectoryError)):
        R._bootstrap_space_ancestor(path)


@pytest.mark.parametrize("free", [-1, None, 0.5, True])
def test_invalid_capacity_is_not_treated_as_unlimited(tmp_path, monkeypatch, free):
    monkeypatch.setattr(R.shutil, "disk_usage", lambda _: SimpleNamespace(free=free))
    with pytest.raises(ValueError):
        require(tmp_path, estimate())
