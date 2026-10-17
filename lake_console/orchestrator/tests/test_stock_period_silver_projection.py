"""Independent expected rows exercise filtering and source-whole-row selection."""

from decimal import Decimal

import pytest

from orchestrator.defs import stock_period_silver as silver
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.run_contracts.stock_period_silver import raw_path
from tests.test_stock_period_silver_contracts import (
    NAMES,
    TYPES,
    A,
    B,
    C,
    literal_row,
    write_raw,
)
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414 -- Explicit pytest fixture re-export.
)


def test_whole_crossyear_listing_and_latest_month_rows(period_fixture, tmp_path):
    f = period_fixture
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=tmp_path / "projection_spill")
    ) as con:
        silver.load_references(con, f["references"])
        for freq, period, expected in [
            ("week", "2014-01-03", [A]),
            ("week", "2020-04-03", [A, B]),
            ("week", "2026-10-16", [A, B, C]),
            ("month", "2020-04", [A, B]),
            ("month", "2026-10", [A, B, C]),
        ]:
            silver.select_period(
                con, raw_path(f["lake"], freq, period), freq, period, asof="2026-10-16"
            )
            assert con.execute(
                "SELECT ts_code FROM silver_selected ORDER BY ts_code"
            ).fetchall() == [(k,) for k in sorted(expected)]
        silver.select_period(
            con,
            raw_path(f["lake"], "month", "2020-02"),
            "month",
            "2020-02",
            asof="2026-10-16",
        )
        row = con.execute("SELECT * FROM silver_selected").fetchone()
        assert row == tuple(
            literal_row(A, "20200229", "month", asof="20261015")[:4]
        ) + tuple(
            None if v is None else Decimal(v)
            for v in literal_row(A, "20200229", "month")[4:]
        )
        assert row[12] == Decimal("11.1400")
        assert row[8] is None and row[20] is None


def test_tied_latest_conflict_rejected_and_identical_values_keep_source_date(
    period_fixture, tmp_path
):
    f = period_fixture
    source = raw_path(f["lake"], "month", "2020-02")
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=tmp_path / "conflict_spill")
    ) as con:
        silver.load_references(con, f["references"])
        write_raw(
            con,
            source,
            [
                literal_row(A, d, "month", qfq=q)
                for d, q in [("20200228", "12.01"), ("20200229", "11.14")]
            ],
        )
        with pytest.raises(ValueError, match="latest_version_conflict"):
            silver.select_period(con, source, "month", "2020-02", asof="2026-10-16")
        write_raw(
            con,
            source,
            [literal_row(A, d, "month") for d in ("20200228", "20200229", "20200229")],
        )
        assert (
            silver.select_period(con, source, "month", "2020-02", asof="2026-10-16")
            == 1
        )
        assert con.execute(
            "SELECT trade_date,end_date FROM silver_selected"
        ).fetchone() == ("20200229", "20261016")


@pytest.mark.parametrize(
    "field,value",
    [
        ("ts_code", "UNKNOWN"),
        ("freq", "month"),
        ("trade_date", "20261009"),
        ("trade_date", "20261399"),
        ("end_date", "20261018"),
    ],
)
def test_bad_identity_frequency_date_or_partition_rejected(
    period_fixture, tmp_path, field, value
):
    f = period_fixture
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=tmp_path / "invalid_spill")
    ) as con:
        silver.load_references(con, f["references"])
        row = literal_row(A, "20261016", "week")
        row[NAMES.index(field)] = value
        source = raw_path(f["lake"], "week", "2026-10-16")
        write_raw(con, source, [row])
        with pytest.raises(ValueError, match="identity_date_or_partition"):
            silver.select_period(con, source, "week", "2026-10-16", asof="2026-10-16")


@pytest.mark.parametrize(
    "change",
    [
        "date_type",
        "double",
        "rename",
        "extra",
        "price",
        "null",
        "code",
        "missing",
        "duplicate",
    ],
)
def test_candidate_contract_or_whole_row_drift_fails(period_fixture, tmp_path, change):
    f = period_fixture
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=tmp_path / "candidate_spill")
    ) as con:
        silver.load_references(con, f["references"])
        silver.select_period(
            con,
            raw_path(f["lake"], "month", "2020-02"),
            "month",
            "2020-02",
            asof="2026-10-16",
        )
        query = "SELECT * FROM silver_selected"
        replacements = {
            "date_type": "SELECT * REPLACE (strptime(trade_date,'%Y%m%d')::DATE AS trade_date) FROM silver_selected",
            "double": "SELECT * REPLACE (close::DOUBLE AS close) FROM silver_selected",
            "rename": 'SELECT * EXCLUDE ("change"),"change" AS change_amount FROM silver_selected',
            "extra": "SELECT *, '2020-02' AS period FROM silver_selected",
            "price": "SELECT * REPLACE ((close+1)::DECIMAL(18,4) AS close) FROM silver_selected",
            "null": "SELECT * REPLACE (0::DECIMAL(18,4) AS pre_close) FROM silver_selected",
            "code": "SELECT * REPLACE ('920000.BJ' AS ts_code) FROM silver_selected",
            "missing": "SELECT * FROM silver_selected WHERE FALSE",
            "duplicate": "SELECT * FROM silver_selected UNION ALL SELECT * FROM silver_selected",
        }
        candidate = tmp_path / "bad.parquet"
        con.execute(
            f"COPY ({replacements.get(change, query)}) TO ? (FORMAT PARQUET)",
            [str(candidate)],
        )
        with pytest.raises(
            ValueError, match="silver_(schema|key_partition|source_projection)"
        ):
            silver.validate_projection(con, candidate, "month", "2020-02")


def test_raw_schema_has_independent_literal_contract(period_fixture, tmp_path):
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=tmp_path / "schema_spill")
    ) as con:
        actual = con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(raw_path(period_fixture["lake"], "week", "2014-01-03"))],
        ).fetchall()
        assert [(r[0], r[1]) for r in actual] == list(zip(NAMES, TYPES, strict=True))
