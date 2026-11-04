"""Literal LLD 18.6.1 history budgets using integers and temporary directories.

Expected byte counts are independent hand calculations from the approved row,
file, record and device estimates. Capacity is injected; no source request,
formal resource, large file or memory pressure is used.
"""

import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest
from duckdb import Error as DuckDBError

from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.run_contracts import stk_factor_pro as contracts


def estimate(**changes):
    values = {
        "unit_row_bounds": (4,),
        "max_batch_rows": 1,
        "remaining_layer_row_bounds": (3, 3),
        "remaining_record_file_count": 9,
        "day_work_bytes": 1_073_741_824,
    }
    values.update(changes)
    return history.estimate_stk_factor_pro_history_space(**values)


def test_friday_to_monday_source_includes_t_and_two_layers_have_literal_bytes():
    # Source: Friday through Monday(T) = 4 natural dates. Only Friday is an
    # earlier opening date, so the current publication batch has at most 1 row.
    # P(4)=4,211,016, P(1)=4,198,482, P(3)=4,206,838.
    actual = estimate()
    assert actual == contracts.BootstrapSpaceEstimate(
        source_bytes=4_211_016,
        candidate_bytes=8_413_676,
        temp_bytes=1_082_151_322,
        record_bytes=9_437_184,
    )
    # Evidence Parquet and the complete SQL source coexist: neither replaces
    # the other in the task's additional-space estimate.
    assert actual.source_bytes + actual.temp_bytes == 1_086_362_338


def test_two_unit_files_keep_separate_overheads_but_one_complete_source_relation():
    # P(4)+P(2)=8,413,676; H=P(6)=4,219,372; B20=P(2)=4,202,660.
    actual = estimate(
        unit_row_bounds=(4, 2),
        max_batch_rows=2,
        remaining_layer_row_bounds=(4, 4),
    )
    assert actual == contracts.BootstrapSpaceEstimate(
        source_bytes=8_413_676,
        candidate_bytes=8_422_032,
        temp_bytes=1_082_163_856,
        record_bytes=9_437_184,
    )


def test_forty_five_dates_budget_every_candidate_without_materializing_history():
    # One 64-natural-day source, 20 rows per publication batch, 45 dates with
    # two 3-row candidates each. The final batch has 5 dates, not 20 more.
    actual = estimate(
        unit_row_bounds=(64,),
        max_batch_rows=20,
        remaining_layer_row_bounds=(3,) * 90,
        remaining_record_file_count=273,
    )
    assert actual == contracts.BootstrapSpaceEstimate(
        source_bytes=4_461_696,
        candidate_bytes=378_615_420,
        temp_bytes=1_082_481_384,
        record_bytes=286_261_248,
    )


def test_capacity_groups_same_device_before_adding_one_margin(tmp_path, monkeypatch):
    staging, temp = tmp_path / "staging", tmp_path / "temp"
    staging.mkdir()
    temp.mkdir()
    observed = []

    def capacity(path):
        observed.append(Path(path))
        # S+C+J+T=1,104,213,198, plus exactly one 16MiB device margin.
        return SimpleNamespace(free=1_120_990_414)

    monkeypatch.setattr(history.shutil, "disk_usage", capacity)
    history.require_stk_factor_pro_history_space(
        required_by_path=(
            (staging, 22_061_876),
            (temp, 1_082_151_322),
        ),
        run_id="run-space",
        stage="历史下载前",
    )
    assert len(observed) == 1

    monkeypatch.setattr(
        history.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=1_120_990_413),
    )
    with pytest.raises(dg.Failure, match="空间不足") as caught:
        history.require_stk_factor_pro_history_space(
            required_by_path=((staging, 22_061_876), (temp, 1_082_151_322)),
            run_id="run-space",
            stage="历史下载前",
        )
    assert caught.value.metadata["required_bytes"].value == 1_120_990_414
    assert caught.value.metadata["retryable"].value is False
    assert caught.value.metadata["source_error_code"].value is None


def test_different_devices_each_keep_their_own_capacity_and_margin(
    tmp_path, monkeypatch
):
    staging, temp = tmp_path / "staging", tmp_path / "temp"
    staging.mkdir()
    temp.mkdir()
    actual_stat = Path.stat
    observed = []

    def separate_devices(path, *args, **kwargs):
        value = actual_stat(path, *args, **kwargs)
        if path not in (staging, temp):
            return value
        fields = list(value)
        fields[2] = 101 if path == staging else 202
        return os.stat_result(fields)

    def capacity(path):
        observed.append(Path(path))
        return SimpleNamespace(free=38_839_092 if path == staging else 1_098_928_538)

    monkeypatch.setattr(Path, "stat", separate_devices)
    monkeypatch.setattr(history.shutil, "disk_usage", capacity)
    history.require_stk_factor_pro_history_space(
        required_by_path=((staging, 22_061_876), (temp, 1_082_151_322)),
        run_id="run-space",
        stage="历史下载前",
    )
    assert observed == [staging, temp]

    # Space on the staging device cannot compensate for one missing byte on
    # the independent temporary device.
    monkeypatch.setattr(
        history.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(
            free=10_000_000_000 if path == staging else 1_098_928_537
        ),
    )
    with pytest.raises(dg.Failure, match="空间不足") as caught:
        history.require_stk_factor_pro_history_space(
            required_by_path=((staging, 22_061_876), (temp, 1_082_151_322)),
            run_id="run-space",
            stage="历史下载前",
        )
    assert caught.value.metadata["required_bytes"].value == 1_098_928_538


class SpillMetadata:
    """Only current database spill metadata is injected, never business rows."""

    def __init__(self, connection, files):
        self.connection, self.files = connection, files
        self.queries = []

    def execute(self, statement, parameters=None):
        self.queries.append(str(statement))
        if "duckdb_temporary_files()" in str(statement):
            return SimpleNamespace(fetchall=lambda: self.files)
        if parameters is None:
            return self.connection.execute(statement)
        return self.connection.execute(statement, parameters)


@pytest.fixture
def space_inputs(tmp_path):
    from orchestrator.defs.paths import (
        raw_stk_factor_pro_path,
        silver_stock_factor_pro_path,
    )
    from tests.stk_factor_pro_history_test_support import connection, roots, row
    from tests.test_stk_factor_pro_history_publication_batches import write_rows

    friday, monday = date(2026, 10, 30), date(2026, 11, 2)
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        values = (row("000001.SZ", "20261030"), row("600000.SH", "20261030"))
        write_rows(
            conn, raw_stk_factor_pro_path(lake, friday.isoformat()), values, layer="raw"
        )
        write_rows(
            conn,
            silver_stock_factor_pro_path(lake, friday.isoformat()),
            values,
            layer="silver",
        )
        yield (
            conn,
            {
                "identity": contracts.RunIdentity(
                    "run-space", None, monday, monday, friday, "today", 0, None, None
                ),
                "expected_units": (
                    contracts.UnitProjection(5, "000001.SZ", None, friday, monday),
                ),
                "publication_dates": (friday,),
                "lake_root": lake,
                "staging_root": staging,
                "known_records": {},
                "basis_row_counts": (2, 2, 2),
            },
        )


def test_spill_already_on_disk_is_not_reserved_twice_and_budget_is_computed_once(
    space_inputs, monkeypatch
):
    conn, inputs = space_inputs
    temporary = Path(
        conn.execute("SELECT current_setting('temp_directory')").fetchone()[0]
    )
    observed = SpillMetadata(
        conn, [(str(temporary / "duckdb_temp_storage.tmp"), 4_211_016)]
    )
    original_estimate = history.estimate_stk_factor_pro_history_space
    estimates = []

    def once(**kwargs):
        estimates.append(kwargs)
        return original_estimate(**kwargs)

    monkeypatch.setattr(history, "estimate_stk_factor_pro_history_space", once)
    # This factory has not saved eligibility yet, so it reserves one additional
    # 1MiB record beyond the pure k=9 sample.
    monkeypatch.setattr(
        history.shutil, "disk_usage", lambda path: SimpleNamespace(free=1_117_827_974)
    )
    check = history.build_stk_factor_pro_history_space_check(observed, **inputs)
    check("历史会话前", path=inputs["staging_root"])
    check("领取下一unit前", path=inputs["staging_root"])
    assert len(estimates) == 1
    assert sum("parquet_file_metadata" in query for query in observed.queries) == 1
    assert sum("duckdb_temporary_files()" in query for query in observed.queries) == 2
    assert estimates[0]["remaining_record_file_count"] == 10

    observed.files = []
    with pytest.raises(dg.Failure, match="空间不足") as caught:
        check("无已占spill时", path=inputs["staging_root"])
    assert caught.value.metadata["required_bytes"].value == 1_122_038_990


def test_final_statistics_does_not_read_spill_again(space_inputs, monkeypatch):
    conn, inputs = space_inputs
    observed = SpillMetadata(conn, [])
    monkeypatch.setattr(
        history.shutil, "disk_usage", lambda path: SimpleNamespace(free=10_000_000_000)
    )
    check = history.build_stk_factor_pro_history_space_check(observed, **inputs)
    check("历史会话前", path=inputs["staging_root"])
    count = sum("duckdb_temporary_files()" in query for query in observed.queries)
    final = check("最后统计", path=inputs["staging_root"], event="final_statistics")
    assert final == contracts.BootstrapSpaceEstimate(0, 0, 0, 1_048_576)
    assert (
        sum("duckdb_temporary_files()" in query for query in observed.queries) == count
    )


def test_forty_five_dates_plan_twenty_day_work_without_creating_business_files(
    tmp_path, monkeypatch
):
    from tests.stk_factor_pro_history_test_support import connection, identity, roots
    from tests.test_stk_factor_pro_history_publication_batches import T, trading_dates

    dates = trading_dates(45)
    units = (contracts.UnitProjection(5, "000001.SZ", None, dates[0], T),)
    planned = history.plan_stk_factor_pro_history_publication_dates(
        identity=identity(),
        expected_units=units,
        calendar=(*dates, T),
        registered_dates=dates,
    )
    assert planned == dates and len(planned) == 45
    original_estimate = history.estimate_stk_factor_pro_history_space
    calls = []

    def once(**values):
        calls.append(values)
        return original_estimate(**values)

    monkeypatch.setattr(history, "estimate_stk_factor_pro_history_space", once)
    monkeypatch.setattr(
        history.shutil, "disk_usage", lambda path: SimpleNamespace(free=10_000_000_000)
    )
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        check = history.build_stk_factor_pro_history_space_check(
            conn,
            identity=identity(),
            expected_units=units,
            publication_dates=planned,
            lake_root=lake,
            staging_root=staging,
            known_records={},
            basis_row_counts=(1, 1),
        )
        first = check("首批前", path=staging)
        check("第二批前", path=staging)
        check("五日尾批前", path=staging)
    assert len(calls) == 1
    assert calls[0]["max_batch_rows"] == 20
    assert calls[0]["remaining_layer_row_bounds"] == (1,) * 90
    assert calls[0]["remaining_record_file_count"] == 274
    assert first.candidate_bytes == 377_863_380
    assert first.record_bytes == 287_309_824
    assert not tuple(lake.rglob("*.parquet"))
    assert not tuple(staging.rglob("*.parquet"))


def test_initial_capacity_failure_never_starts_a_download_session(
    tmp_path, monkeypatch
):
    from tests.stk_factor_pro_history_test_support import connection
    from tests.test_stk_factor_pro_history_download import (
        P,
        prepare,
        run_download,
        sample_downloader,
    )

    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        args["check_space"] = history.build_stk_factor_pro_history_space_check(
            conn,
            identity=args["identity"],
            expected_units=args["expected_units"],
            publication_dates=(P,),
            lake_root=args["lake_root"],
            staging_root=args["staging_root"],
            known_records=known_records,
            basis_row_counts=(2, 2),
        )
        monkeypatch.setattr(
            history.shutil, "disk_usage", lambda path: SimpleNamespace(free=0)
        )
        downloader = sample_downloader()
        with pytest.raises(dg.Failure, match="空间不足") as caught:
            run_download(conn, args, downloader, known_records=known_records)
        assert not downloader.calls and not downloader.sessions
        assert not (root / "source/history/source-complete.json").exists()
        assert caught.value.metadata["retryable"].value is False
        assert caught.value.metadata["source_error_code"].value is None


def test_already_saved_valid_eligibility_is_not_reserved_as_new_space(
    tmp_path, monkeypatch
):
    from tests.stk_factor_pro_history_test_support import connection
    from tests.test_stk_factor_pro_history_download import P, prepare

    records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=records)
        history.require_stk_factor_pro_history_eligibility(
            args["plan"], args["eligibility"]
        )
        reference = history._json_write(
            root,
            args["identity"],
            "history-eligibility.json",
            args["eligibility"],
            known_records=records,
            check_space=None,
        )
        assert reference.relative_path == "history-eligibility.json"
        assert records[root / reference.relative_path][0] is args["eligibility"]
        monkeypatch.setattr(
            history.shutil,
            "disk_usage",
            lambda path: SimpleNamespace(free=10_000_000_000),
        )
        check = history.build_stk_factor_pro_history_space_check(
            conn,
            identity=args["identity"],
            expected_units=args["expected_units"],
            publication_dates=(P,),
            lake_root=args["lake_root"],
            staging_root=args["staging_root"],
            known_records=records,
            basis_row_counts=(2, 2),
        )
        result = check("历史下载前", path=root)
        assert result.record_bytes == 9_437_184


def test_capacity_loss_stops_before_the_next_unit_is_requested(tmp_path, monkeypatch):
    from tests.stk_factor_pro_history_test_support import connection
    from tests.test_stk_factor_pro_history_download import (
        P,
        assert_no_relations,
        prepare,
        run_download,
        sample_downloader,
    )

    known_records, delivered, order = {}, [], []
    available = {"free": 10_000_000_000}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        actual_check = history.build_stk_factor_pro_history_space_check(
            conn,
            identity=args["identity"],
            expected_units=args["expected_units"],
            publication_dates=(P,),
            lake_root=args["lake_root"],
            staging_root=args["staging_root"],
            known_records=known_records,
            basis_row_counts=(2, 2),
        )
        monkeypatch.setattr(
            history.shutil,
            "disk_usage",
            lambda path: SimpleNamespace(free=available["free"]),
        )

        def check_space(stage, **facts):
            order.append(stage)
            if stage == "领取下一历史unit前" and delivered:
                available["free"] = 0
            return actual_check(stage, **facts)

        def delivered_result(value):
            delivered.append(value.unit.object_code)
            return value

        args["check_space"] = check_space
        args["check_cancel"] = lambda: order.append("cancel")
        downloader = sample_downloader(result_transform=delivered_result)
        with pytest.raises(dg.Failure, match="空间不足"):
            run_download(conn, args, downloader, known_records=known_records)
        assert delivered == ["000001.SZ"]
        assert order[-2:] == ["cancel", "领取下一历史unit前"]
        assert len(downloader.calls) == len(downloader.sessions) == 1
        assert downloader.sessions[0].closed
        assert len(tuple((root / "source/history/units").glob("*.parquet"))) == 1
        assert not (root / "source/history/source-complete.json").exists()
        assert_no_relations(conn)


def assert_local_history_failure(error, *, target_date=None):
    assert error.allow_retries is False
    assert error.metadata["phase"].value == "history"
    assert error.metadata["run_id"].value == "run-space"
    assert error.metadata["retryable"].value is False
    assert error.metadata["source_error_code"].value is None
    if target_date is not None:
        assert error.metadata["target_trade_date"].value == target_date.isoformat()


def test_disk_capacity_io_failure_is_a_local_nonretryable_history_failure(
    tmp_path, monkeypatch
):
    def unavailable(path):
        raise OSError("controlled disk capacity metadata failure")

    monkeypatch.setattr(history.shutil, "disk_usage", unavailable)
    with pytest.raises(dg.Failure, match="元信息") as caught:
        history.require_stk_factor_pro_history_space(
            required_by_path=((tmp_path, 1),),
            run_id="run-space",
            stage="容量读取前",
        )
    assert_local_history_failure(caught.value)
    assert isinstance(caught.value.__cause__, OSError)


def test_initial_duckdb_setting_failure_is_not_reported_as_source_failure(space_inputs):
    conn, inputs = space_inputs

    class MissingSetting(SpillMetadata):
        def execute(self, statement, parameters=None):
            if "current_setting" in str(statement):
                raise DuckDBError("controlled current_setting failure")
            return super().execute(statement, parameters)

    with pytest.raises(dg.Failure, match="元信息") as caught:
        history.build_stk_factor_pro_history_space_check(
            MissingSetting(conn, []), **inputs
        )
    assert_local_history_failure(
        caught.value, target_date=inputs["identity"].target_trade_date
    )
    assert isinstance(caught.value.__cause__, DuckDBError)


def test_running_spill_metadata_failure_stops_without_guessing_zero(space_inputs):
    conn, inputs = space_inputs

    class MissingSpill(SpillMetadata):
        def execute(self, statement, parameters=None):
            if "duckdb_temporary_files()" in str(statement):
                raise DuckDBError("controlled spill metadata failure")
            return super().execute(statement, parameters)

    check = history.build_stk_factor_pro_history_space_check(
        MissingSpill(conn, []), **inputs
    )
    with pytest.raises(dg.Failure, match="元信息") as caught:
        check("领取下一unit前", path=inputs["staging_root"])
    assert_local_history_failure(
        caught.value, target_date=inputs["identity"].target_trade_date
    )
    assert isinstance(caught.value.__cause__, DuckDBError)
