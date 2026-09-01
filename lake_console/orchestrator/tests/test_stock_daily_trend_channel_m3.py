import inspect
import os
from pathlib import Path

import dagster as dg
import duckdb
import pytest

import orchestrator.defs.checks.stock_daily_trend_channel_checks as trend_checks
import orchestrator.defs.stock_daily_trend_channel as trend_channel
from orchestrator.defs.assets.stock_daily_trend_channel import (
    RESULT_ASSET_KEY,
    STATE_ASSET_KEY,
    gold_stock_daily_trend_channel_assets,
)
from orchestrator.defs.checks.stock_daily_trend_channel_checks import (
    gold_stock_daily_trend_channel_contract_check,
    gold_stock_daily_trend_channel_input_coverage_check,
    gold_stock_daily_trend_channel_state_contract_check,
)
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_staging_path,
    gold_stock_daily_trend_channel_state_path,
    gold_stock_daily_trend_channel_state_staging_path,
    silver_stock_basic_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.stock_daily_trend_channel import (
    StockDailyTrendChannelAudit,
    audit_stock_daily_trend_channel_result,
    audit_stock_daily_trend_channel_state,
    audit_stock_daily_trend_channel_state_coverage,
    write_stock_daily_trend_channel_daily_partition,
)

DAY_1 = "2026-08-27"
DAY_2 = "2026-08-28"
DAY_3 = "2026-08-31"


def _write_parquet(connection, path: Path, select_sql: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(f"COPY ({select_sql}) TO '{path}' (FORMAT PARQUET)")


def _write_qfq(
    connection,
    path: Path,
    trade_date: str,
    rows: list[tuple[str, float, float, float, float]],
) -> None:
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE qfq_fixture (
          ts_code VARCHAR,
          trade_date DATE,
          open DOUBLE,
          high DOUBLE,
          low DOUBLE,
          close DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO qfq_fixture VALUES (?, ?, ?, ?, ?, ?)",
        [(code, trade_date, open_, high, low, close) for code, open_, high, low, close in rows],
    )
    _write_parquet(connection, path, "SELECT * FROM qfq_fixture ORDER BY ts_code")


def _write_basic(connection, path: Path, codes: list[str]) -> None:
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE basic_fixture (ts_code VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO basic_fixture VALUES (?)",
        [(code,) for code in codes],
    )
    _write_parquet(connection, path, "SELECT * FROM basic_fixture ORDER BY ts_code")


def _write_lifecycle(
    connection,
    path: Path,
    rows: list[tuple[str, str, str | None]],
) -> None:
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE lifecycle_fixture (
          ts_code VARCHAR,
          is_cny_stock BOOLEAN,
          list_date DATE,
          delist_date DATE
        )
        """
    )
    connection.executemany(
        "INSERT INTO lifecycle_fixture VALUES (?, true, ?, ?)",
        rows,
    )
    _write_parquet(
        connection,
        path,
        "SELECT * FROM lifecycle_fixture ORDER BY ts_code",
    )


def _write_calendar(connection, root: Path, dates: list[str]) -> None:
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE calendar_fixture (
          exchange VARCHAR,
          trade_date DATE,
          is_open BOOLEAN,
          pretrade_date DATE
        )
        """
    )
    connection.executemany(
        "INSERT INTO calendar_fixture VALUES ('SSE', ?, true, NULL)",
        [(trade_date,) for trade_date in dates],
    )
    _write_parquet(
        connection,
        silver_trade_calendar_path(root),
        "SELECT * FROM calendar_fixture ORDER BY trade_date",
    )


def _prepare_inputs(
    *,
    connection,
    root: Path,
    trade_date: str,
    qfq_rows: list[tuple[str, float, float, float, float]],
    lifecycle_rows: list[tuple[str, str, str | None]],
) -> None:
    codes = sorted({row[0] for row in lifecycle_rows})
    _write_qfq(
        connection,
        gold_stock_daily_qfq_path(root, trade_date),
        trade_date,
        qfq_rows,
    )
    _write_basic(connection, silver_stock_basic_path(root), codes)
    _write_lifecycle(connection, silver_stock_lifecycle_path(root), lifecycle_rows)


def _write_day(
    *,
    connection,
    root: Path,
    staging_root: Path,
    run_id: str,
    trade_date: str,
    qfq_rows: list[tuple[str, float, float, float, float]],
    lifecycle_rows: list[tuple[str, str, str | None]],
    previous_trade_date: str | None,
    replace_file=os.replace,
):
    _prepare_inputs(
        connection=connection,
        root=root,
        trade_date=trade_date,
        qfq_rows=qfq_rows,
        lifecycle_rows=lifecycle_rows,
    )
    return write_stock_daily_trend_channel_daily_partition(
        connection=connection,
        trade_date=trade_date,
        qfq_source_path=gold_stock_daily_qfq_path(root, trade_date),
        stock_basic_path=silver_stock_basic_path(root),
        stock_lifecycle_path=silver_stock_lifecycle_path(root),
        previous_trade_date=previous_trade_date,
        previous_state_path=(
            gold_stock_daily_trend_channel_state_path(root, previous_trade_date)
            if previous_trade_date is not None
            else None
        ),
        result_candidate_path=gold_stock_daily_trend_channel_staging_path(
            staging_root,
            run_id,
            trade_date,
        ),
        state_candidate_path=gold_stock_daily_trend_channel_state_staging_path(
            staging_root,
            run_id,
            trade_date,
        ),
        result_target_path=gold_stock_daily_trend_channel_path(root, trade_date),
        state_target_path=gold_stock_daily_trend_channel_state_path(
            root,
            trade_date,
        ),
        replace_file=replace_file,
    )


def _rows(connection, path: Path) -> list[tuple]:
    return connection.execute(
        f"SELECT * FROM read_parquet('{path}') ORDER BY ts_code"
    ).fetchall()


def _check_context(root: Path, partition_key: str):
    return dg.build_op_context(
        partition_key=partition_key,
        resources={
            "lake_root": LakeRootResource(root_path=str(root)),
            "duckdb": DuckDBResource(),
        },
    )


def _metadata_value(result: dg.AssetCheckResult, key: str):
    value = result.metadata[key]
    return getattr(value, "data", getattr(value, "value", value))


def test_multi_asset_contract_is_paired_partitioned_and_non_subsettable() -> None:
    assert gold_stock_daily_trend_channel_assets.can_subset is False
    assert {
        key.to_user_string() for key in gold_stock_daily_trend_channel_assets.keys
    } == {RESULT_ASSET_KEY, STATE_ASSET_KEY}
    for asset_key in gold_stock_daily_trend_channel_assets.keys:
        spec = gold_stock_daily_trend_channel_assets.get_asset_spec(asset_key)
        assert spec.partitions_def.name == "cn_a_stock_daily_trend_channel_trade_days"
        assert spec.group_name == "quote"
        assert {
            dependency.asset_key.to_user_string() for dependency in spec.deps
        } == {
            "gold_stock_daily_qfq",
            "silver_stock_basic",
            "silver_stock_lifecycle",
            "silver_trade_calendar",
        }


def test_normal_day_writes_result_and_state(tmp_path: Path) -> None:
    connection = duckdb.connect()
    try:
        result = _write_day(
            connection=connection,
            root=tmp_path / "lake",
            staging_root=tmp_path / "staging",
            run_id="normal",
            trade_date=DAY_1,
            qfq_rows=[
                ("000001.SZ", 10.0, 11.0, 9.0, 10.5),
                ("600000.SH", 20.0, 21.0, 19.0, 20.5),
            ],
            lifecycle_rows=[
                ("000001.SZ", "1991-01-01", None),
                ("600000.SH", "1999-01-01", None),
            ],
            previous_trade_date=None,
        )
        assert result.output_row_count == 2
        assert result.observed_state_row_count == 2
        assert result.carried_state_row_count == 0
        assert result.uninitialized_lifecycle_code_count == 0
        assert result.result_path.exists()
        assert result.state_path.exists()
        assert not result.result_candidate_path.exists()
        assert not result.state_candidate_path.exists()
    finally:
        connection.close()


def test_suspended_stock_is_carried_in_state_but_not_result(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    lifecycle = [
        ("000001.SZ", "1991-01-01", None),
        ("600000.SH", "1999-01-01", None),
    ]
    connection = duckdb.connect()
    try:
        _write_day(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="day-1",
            trade_date=DAY_1,
            qfq_rows=[
                ("000001.SZ", 10.0, 11.0, 9.0, 10.5),
                ("600000.SH", 20.0, 21.0, 19.0, 20.5),
            ],
            lifecycle_rows=lifecycle,
            previous_trade_date=None,
        )
        result = _write_day(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="day-2",
            trade_date=DAY_2,
            qfq_rows=[("000001.SZ", 10.5, 11.5, 9.5, 11.0)],
            lifecycle_rows=lifecycle,
            previous_trade_date=DAY_1,
        )
        assert [row[0] for row in _rows(connection, result.result_path)] == [
            "000001.SZ"
        ]
        state_rows = _rows(connection, result.state_path)
        assert [row[0] for row in state_rows] == ["000001.SZ", "600000.SH"]
        carried = next(row for row in state_rows if row[0] == "600000.SH")
        assert carried[2].isoformat() == DAY_1
        assert carried[3] is False
        assert result.observed_state_row_count == 1
        assert result.carried_state_row_count == 1
    finally:
        connection.close()


def test_new_listing_stays_uninitialized_until_first_qfq(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    connection = duckdb.connect()
    try:
        _write_day(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="listing-day-1",
            trade_date=DAY_1,
            qfq_rows=[("000001.SZ", 10.0, 11.0, 9.0, 10.5)],
            lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
            previous_trade_date=None,
        )
        day_2 = _write_day(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="listing-day-2",
            trade_date=DAY_2,
            qfq_rows=[("000001.SZ", 10.5, 11.5, 9.5, 11.0)],
            lifecycle_rows=[
                ("000001.SZ", "1991-01-01", None),
                ("301999.SZ", DAY_2, None),
            ],
            previous_trade_date=DAY_1,
        )
        assert day_2.uninitialized_lifecycle_code_count == 1
        assert "301999.SZ" not in [row[0] for row in _rows(connection, day_2.state_path)]

        day_3 = _write_day(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="listing-day-3",
            trade_date=DAY_3,
            qfq_rows=[
                ("000001.SZ", 11.0, 12.0, 10.0, 11.5),
                ("301999.SZ", 30.0, 31.0, 29.0, 30.5),
            ],
            lifecycle_rows=[
                ("000001.SZ", "1991-01-01", None),
                ("301999.SZ", DAY_2, None),
            ],
            previous_trade_date=DAY_2,
        )
        new_state = next(
            row for row in _rows(connection, day_3.state_path) if row[0] == "301999.SZ"
        )
        assert new_state[2].isoformat() == DAY_3
        assert new_state[3] is True
    finally:
        connection.close()


def test_delist_date_is_exclusive_and_state_exits_on_boundary(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    connection = duckdb.connect()
    try:
        _write_day(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="delist-day-1",
            trade_date=DAY_1,
            qfq_rows=[("600000.SH", 20.0, 21.0, 19.0, 20.5)],
            lifecycle_rows=[("600000.SH", "1999-01-01", DAY_2)],
            previous_trade_date=None,
        )
        result = _write_day(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="delist-day-2",
            trade_date=DAY_2,
            qfq_rows=[("000001.SZ", 10.0, 11.0, 9.0, 10.5)],
            lifecycle_rows=[
                ("000001.SZ", "1991-01-01", None),
                ("600000.SH", "1999-01-01", DAY_2),
            ],
            previous_trade_date=DAY_1,
        )
        assert [row[0] for row in _rows(connection, result.state_path)] == [
            "000001.SZ"
        ]
    finally:
        connection.close()


def test_existing_target_blocks_before_candidate_write(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    connection = duckdb.connect()
    try:
        _prepare_inputs(
            connection=connection,
            root=root,
            trade_date=DAY_1,
            qfq_rows=[("000001.SZ", 10.0, 11.0, 9.0, 10.5)],
            lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
        )
        result_target = gold_stock_daily_trend_channel_path(root, DAY_1)
        _write_parquet(connection, result_target, "SELECT 1 AS occupied")
        with pytest.raises(FileExistsError, match="no-overwrite"):
            _write_day(
                connection=connection,
                root=root,
                staging_root=staging,
                run_id="occupied",
                trade_date=DAY_1,
                qfq_rows=[("000001.SZ", 10.0, 11.0, 9.0, 10.5)],
                lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
                previous_trade_date=None,
            )
        assert not gold_stock_daily_trend_channel_staging_path(
            staging, "occupied", DAY_1
        ).exists()
    finally:
        connection.close()


def test_both_candidates_exist_before_failed_validation_and_no_target_promotes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    failed_audit = StockDailyTrendChannelAudit(
        passed=False,
        checked_row_count=1,
        failed_row_count=1,
        source_row_count=1,
        output_row_count=1,
        failure_rule_counts={"forced_state_failure": 1},
        failure_samples={},
        observed_columns=(),
    )
    monkeypatch.setattr(
        trend_channel,
        "audit_stock_daily_trend_channel_state",
        lambda **_: failed_audit,
    )
    connection = duckdb.connect()
    try:
        with pytest.raises(ValueError, match="candidate audit failed"):
            _write_day(
                connection=connection,
                root=root,
                staging_root=staging,
                run_id="invalid-candidate",
                trade_date=DAY_1,
                qfq_rows=[("000001.SZ", 10.0, 11.0, 9.0, 10.5)],
                lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
                previous_trade_date=None,
            )
        assert gold_stock_daily_trend_channel_staging_path(
            staging, "invalid-candidate", DAY_1
        ).exists()
        assert gold_stock_daily_trend_channel_state_staging_path(
            staging, "invalid-candidate", DAY_1
        ).exists()
        assert not gold_stock_daily_trend_channel_path(root, DAY_1).exists()
        assert not gold_stock_daily_trend_channel_state_path(root, DAY_1).exists()
    finally:
        connection.close()


def test_second_promotion_failure_restores_state_candidate(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    call_count = 0

    def _fail_second_replace(source: Path, target: Path) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("forced result promotion failure")
        os.replace(source, target)

    connection = duckdb.connect()
    try:
        with pytest.raises(OSError, match="forced result promotion failure"):
            _write_day(
                connection=connection,
                root=root,
                staging_root=staging,
                run_id="promotion-failure",
                trade_date=DAY_1,
                qfq_rows=[("000001.SZ", 10.0, 11.0, 9.0, 10.5)],
                lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
                previous_trade_date=None,
                replace_file=_fail_second_replace,
            )
        assert gold_stock_daily_trend_channel_staging_path(
            staging, "promotion-failure", DAY_1
        ).exists()
        assert gold_stock_daily_trend_channel_state_staging_path(
            staging, "promotion-failure", DAY_1
        ).exists()
        assert not gold_stock_daily_trend_channel_path(root, DAY_1).exists()
        assert not gold_stock_daily_trend_channel_state_path(root, DAY_1).exists()
    finally:
        connection.close()


def test_invalid_previous_state_version_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    connection = duckdb.connect()
    try:
        day_1 = _write_day(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="version-day-1",
            trade_date=DAY_1,
            qfq_rows=[("000001.SZ", 10.0, 11.0, 9.0, 10.5)],
            lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
            previous_trade_date=None,
        )
        bad_state = day_1.state_path.with_name("bad-state.parquet")
        _write_parquet(
            connection,
            bad_state,
            f"""
            SELECT * REPLACE ('invalid-version' AS formula_version)
            FROM read_parquet('{day_1.state_path}')
            """,
        )
        os.replace(bad_state, day_1.state_path)
        with pytest.raises(ValueError, match="Previous.*state is invalid"):
            _write_day(
                connection=connection,
                root=root,
                staging_root=staging,
                run_id="version-day-2",
                trade_date=DAY_2,
                qfq_rows=[("000001.SZ", 10.5, 11.5, 9.5, 11.0)],
                lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
                previous_trade_date=DAY_1,
            )
    finally:
        connection.close()


def test_qfq_code_outside_lifecycle_fails_closed(tmp_path: Path) -> None:
    connection = duckdb.connect()
    try:
        with pytest.raises(ValueError, match="qfq_lifecycle_membership"):
            _write_day(
                connection=connection,
                root=tmp_path / "lake",
                staging_root=tmp_path / "staging",
                run_id="outside-lifecycle",
                trade_date=DAY_1,
                qfq_rows=[("600000.SH", 20.0, 21.0, 19.0, 20.5)],
                lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
                previous_trade_date=None,
            )
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("qfq_rows", "failure_rule"),
    [
        (
            [
                ("000001.SZ", 10.0, 11.0, 9.0, 10.5),
                ("000001.SZ", 10.0, 11.0, 9.0, 10.5),
            ],
            "qfq_unique_key",
        ),
        (
            [("000001.SZ", 0.0, 11.0, 9.0, 10.5)],
            "qfq_ohlc_valid",
        ),
        (
            [("000001.SZ", 10.0, 11.0, 10.2, 10.5)],
            "qfq_ohlc_valid",
        ),
        (
            [("000001.SZ", 10.0, float("nan"), 9.0, 10.5)],
            "qfq_ohlc_valid",
        ),
    ],
)
def test_invalid_qfq_key_and_ohlc_rules_fail_closed(
    tmp_path: Path,
    qfq_rows: list[tuple[str, float, float, float, float]],
    failure_rule: str,
) -> None:
    connection = duckdb.connect()
    try:
        with pytest.raises(ValueError, match=failure_rule):
            _write_day(
                connection=connection,
                root=tmp_path / "lake",
                staging_root=tmp_path / "staging",
                run_id=failure_rule,
                trade_date=DAY_1,
                qfq_rows=qfq_rows,
                lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
                previous_trade_date=None,
            )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "bad_state_sql",
    [
        "SELECT * FROM original_state UNION ALL SELECT * FROM original_state",
        """
        SELECT * REPLACE (CAST(-1.0 AS DOUBLE) AS short_upper_raw)
        FROM original_state
        """,
        """
        SELECT * REPLACE (
          CAST(8.0 AS DOUBLE) AS short_upper_raw,
          CAST(9.0 AS DOUBLE) AS short_lower_raw
        )
        FROM original_state
        """,
    ],
)
def test_invalid_previous_state_key_raw_and_band_rules_fail_closed(
    tmp_path: Path,
    bad_state_sql: str,
) -> None:
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    connection = duckdb.connect()
    try:
        day_1 = _write_day(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="bad-state-day-1",
            trade_date=DAY_1,
            qfq_rows=[("000001.SZ", 10.0, 11.0, 9.0, 10.5)],
            lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
            previous_trade_date=None,
        )
        connection.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW original_state AS
            SELECT * FROM read_parquet('{day_1.state_path}')
            """
        )
        bad_state_path = day_1.state_path.with_name("invalid-state.parquet")
        _write_parquet(connection, bad_state_path, bad_state_sql)
        os.replace(bad_state_path, day_1.state_path)
        with pytest.raises(ValueError, match="Previous.*state is invalid"):
            _write_day(
                connection=connection,
                root=root,
                staging_root=staging,
                run_id="bad-state-day-2",
                trade_date=DAY_2,
                qfq_rows=[("000001.SZ", 10.5, 11.5, 9.5, 11.0)],
                lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
                previous_trade_date=DAY_1,
            )
    finally:
        connection.close()


def test_shared_audits_and_all_three_ordinary_checks_cover_positive_and_negative(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    connection = duckdb.connect()
    try:
        _write_calendar(connection, root, [DAY_1])
        result = _write_day(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="checks",
            trade_date=DAY_1,
            qfq_rows=[("000001.SZ", 10.0, 11.0, 9.0, 10.5)],
            lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
            previous_trade_date=None,
        )
        assert audit_stock_daily_trend_channel_result(
            connection=connection,
            result_path=result.result_path,
            qfq_source_path=result.qfq_source_path,
            trade_date=DAY_1,
        ).passed
        assert audit_stock_daily_trend_channel_state(
            connection=connection,
            state_path=result.state_path,
            stock_lifecycle_path=result.stock_lifecycle_path,
            trade_date=DAY_1,
        ).passed
        assert audit_stock_daily_trend_channel_state_coverage(
            connection=connection,
            state_path=result.state_path,
            qfq_source_path=result.qfq_source_path,
            stock_lifecycle_path=result.stock_lifecycle_path,
            previous_state_path=None,
            trade_date=DAY_1,
        ).passed

        check_context = _check_context(root, DAY_1)
        assert gold_stock_daily_trend_channel_contract_check(check_context).passed
        assert gold_stock_daily_trend_channel_state_contract_check(
            check_context
        ).passed
        assert gold_stock_daily_trend_channel_input_coverage_check(
            check_context
        ).passed

        bad_result = result.result_path.with_name("bad-result.parquet")
        _write_parquet(
            connection,
            bad_result,
            f"""
            SELECT * REPLACE ('invalid-version' AS formula_version)
            FROM read_parquet('{result.result_path}')
            """,
        )
        os.replace(bad_result, result.result_path)
        failed_result = gold_stock_daily_trend_channel_contract_check(check_context)
        assert not failed_result.passed
        assert _metadata_value(
            failed_result,
            "goldenshare/failure_rule_counts",
        )["formula_version_matches"] == 1

        bad_state = result.state_path.with_name("bad-state.parquet")
        _write_parquet(
            connection,
            bad_state,
            f"""
            SELECT * REPLACE (CAST(-1.0 AS DOUBLE) AS short_upper_raw)
            FROM read_parquet('{result.state_path}')
            """,
        )
        os.replace(bad_state, result.state_path)
        failed_state = gold_stock_daily_trend_channel_state_contract_check(
            check_context
        )
        assert not failed_state.passed
        assert _metadata_value(
            failed_state,
            "goldenshare/failure_rule_counts",
        )["raw_channel_values_valid"] == 1

        empty_state = result.state_path.with_name("empty-state.parquet")
        _write_parquet(
            connection,
            empty_state,
            f"SELECT * FROM read_parquet('{result.state_path}') WHERE false",
        )
        os.replace(empty_state, result.state_path)
        failed_coverage = gold_stock_daily_trend_channel_input_coverage_check(
            check_context
        )
        assert not failed_coverage.passed
        assert _metadata_value(
            failed_coverage,
            "goldenshare/failure_rule_counts",
        )["missing_state"] == 1
    finally:
        connection.close()


def test_candidate_and_checks_reference_the_same_public_audit_helpers() -> None:
    assert trend_channel.audit_stock_daily_trend_channel_result is (
        audit_stock_daily_trend_channel_result
    )
    assert trend_channel.audit_stock_daily_trend_channel_state is (
        audit_stock_daily_trend_channel_state
    )
    assert trend_channel.audit_stock_daily_trend_channel_state_coverage is (
        audit_stock_daily_trend_channel_state_coverage
    )
    writer_source = inspect.getsource(
        trend_channel.write_stock_daily_trend_channel_daily_partition
    )
    check_source = Path(trend_checks.__file__).read_text(encoding="utf-8")
    for helper_name in (
        "audit_stock_daily_trend_channel_result",
        "audit_stock_daily_trend_channel_state",
        "audit_stock_daily_trend_channel_state_coverage",
    ):
        assert helper_name in writer_source
        assert helper_name in check_source


def test_result_audit_rejects_extra_file_and_wrong_partition_path(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect()
    try:
        result = _write_day(
            connection=connection,
            root=tmp_path / "lake",
            staging_root=tmp_path / "staging",
            run_id="path-contract",
            trade_date=DAY_1,
            qfq_rows=[("000001.SZ", 10.0, 11.0, 9.0, 10.5)],
            lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
            previous_trade_date=None,
        )
        extra_path = result.result_path.with_name("extra.parquet")
        _write_parquet(
            connection,
            extra_path,
            f"SELECT * FROM read_parquet('{result.result_path}')",
        )
        extra_audit = audit_stock_daily_trend_channel_result(
            connection=connection,
            result_path=result.result_path,
            qfq_source_path=result.qfq_source_path,
            trade_date=DAY_1,
        )
        assert not extra_audit.passed
        assert extra_audit.failure_rule_counts["single_partition_file"] == 1
        extra_path.unlink()

        wrong_path = tmp_path / "wrong-partition" / "part-000.parquet"
        _write_parquet(
            connection,
            wrong_path,
            f"SELECT * FROM read_parquet('{result.result_path}')",
        )
        wrong_path_audit = audit_stock_daily_trend_channel_result(
            connection=connection,
            result_path=wrong_path,
            qfq_source_path=result.qfq_source_path,
            trade_date=DAY_1,
        )
        assert not wrong_path_audit.passed
        assert wrong_path_audit.failure_rule_counts["partition_path_matches"] == 1
    finally:
        connection.close()
