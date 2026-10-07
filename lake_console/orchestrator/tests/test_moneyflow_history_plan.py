"""Pure planning acceptance from P0 evidence, with no formal-resource access."""

import ast
import csv
from dataclasses import replace
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    MoneyflowHistoryDateCount as Count,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    build_moneyflow_history_plan as build,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    history_schema,
    history_source_key_fields,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    moneyflow_history_export_sql as sql,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    validate_moneyflow_history_plan as validate,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError

# Independent frozen P0 baseline, not generated from the planner under test.
BASELINE = {
    "moneyflow": (14089300, 4067, 141, 217, 99839),
    "moneyflow_cnt_ths": (192009, 495, 26, 26, 7890),
    "moneyflow_dc": (4278673, 739, 46, 46, 99888),
    "moneyflow_ind_dc": (364012, 739, 40, 40, 20620),
    "moneyflow_ind_ths": (44460, 494, 26, 26, 1800),
    "moneyflow_mkt_dc": (839, 839, 44, 44, 20),
    "moneyflow_ths": (2191645, 431, 24, 24, 99070),
}


def p0_counts(dataset):
    report = (
        Path(__file__).resolve().parents[2]
        / "reports/moneyflow_p0_prod_date_counts_20261006.csv"
    )
    with report.open(newline="") as handle:
        return tuple(
            Count(
                row["trade_date"],
                int(row["row_count"]),
                int(row["distinct_business_keys"]),
            )
            for row in csv.DictReader(handle)
            if row["dataset"] == dataset
        )


def small(dataset="moneyflow_dc", rows=1):
    return build(dataset, (Count("2026-09-30", rows, rows),), cutoff="2026-09-30")


@pytest.mark.parametrize("dataset", BASELINE)
def test_p0_whole_scope_matches_independent_baseline(dataset):
    facts = p0_counts(dataset)
    plan = build(dataset, facts, cutoff="2026-09-30")
    rows, dates, units, windows, max_rows = BASELINE[dataset]
    assert (
        plan.row_count,
        len(plan.date_counts),
        len(plan.source_units),
        len(plan.windows),
    ) == (rows, dates, units, windows)
    assert max(w.row_count for w in plan.windows) == max_rows
    assert plan.formal_file_count == 2 * dates
    assert sum(u.row_count for u in plan.source_units) == rows
    assert tuple(day for w in plan.windows for day in w.dates) == tuple(
        f.trade_date for f in facts
    )
    assert all(
        len(w.dates) <= 20
        and w.row_count <= 100000
        and len({d[:4] for d in w.dates}) == 1
        for w in plan.windows
    )
    assert build(dataset, reversed(facts), cutoff="2026-09-30") == plan
    validate(plan)
    if dataset != "moneyflow":
        assert all(
            u.dates == w.dates and u.row_count == w.row_count
            for u, w in zip(plan.source_units, plan.windows, strict=True)
        )
    else:
        assert not any(u.dates for u in plan.source_units)
        assert plan.source_units[-1].row_count == 89300


def test_year_date_and_row_boundaries_are_separate():
    facts = (
        Count("2025-12-31", 1, 1),
        Count("2026-01-02", 60000, 60000),
        Count("2026-01-05", 40000, 40000),
        Count("2026-01-06", 1, 1),
    )
    plan = build("moneyflow_dc", facts, cutoff="2026-09-30")
    assert [w.row_count for w in plan.windows] == [1, 100000, 1]
    assert len(plan.source_units) == 3
    # Read keyset units cross years; write windows still split at year boundaries.
    ordinary = build("moneyflow", facts, cutoff="2026-09-30")
    assert len(ordinary.source_units) == 2
    assert ordinary.windows == plan.windows
    twenty_one = tuple(Count(f"2026-01-{day:02d}", 1, 1) for day in range(1, 22))
    assert [
        len(w.dates)
        for w in build("moneyflow_dc", twenty_one, cutoff="2026-09-30").windows
    ] == [20, 1]


def test_source_gaps_low_coverage_and_early_dc_industry_are_preserved():
    plan = build("moneyflow_ths", p0_counts("moneyflow_ths"), cutoff="2026-09-30")
    facts = {f.trade_date: f.row_count for f in plan.date_counts}
    assert [facts[d] for d in ("2024-12-19", "2024-12-20", "2024-12-23")] == [2, 2, 2]
    gapped = build(
        "moneyflow_cnt_ths", p0_counts("moneyflow_cnt_ths"), cutoff="2026-09-30"
    )
    assert not {"2024-11-04", "2025-01-20", "2026-07-09"} & {
        f.trade_date for f in gapped.date_counts
    }
    assert small("moneyflow_ind_dc", rows=87).row_count == 87
    early = build(
        "moneyflow_ind_dc", (Count("2023-09-12", 87, 87),), cutoff="2026-09-30"
    )
    assert "content_type" in sql(early, 0)
    assert "行业" not in sql(early, 0) and "概念" not in sql(early, 0)


@pytest.mark.parametrize(
    "dataset",
    (
        "biying",
        "stockdb.public",
        "hsgt",
        "unknown_moneyflow",
        "moneyflow;DELETE",
        "raw_tushare.moneyflow",
    ),
)
def test_unapproved_identity_rejected(dataset):
    with pytest.raises(MoneyflowContractError):
        small(dataset)


@pytest.mark.parametrize(
    "facts",
    (
        (),
        (Count("2026-09-30", 1, 1),) * 2,
        (Count("2026-09-31", 1, 1),),
        (Count("2026-10-08", 1, 1),),
        (Count("20260930", 1, 1),),
        (Count("2026-09-30", 0, 0),),
        (Count("2026-09-30", -1, -1),),
        (Count("2026-09-30", 100001, 100001),),
        (Count("2026-09-30", 2, 1),),
        (Count("2026-09-30", True, True),),
        (Count("2026-09-30", 1.0, 1),),
        (Count("2026-09-30", 1, True),),
        ({"trade_date": "2026-09-30"},),
    ),
)
def test_invalid_scope_rejected_before_sql(facts):
    with pytest.raises(MoneyflowContractError):
        build("moneyflow_dc", facts, cutoff="2026-09-30")


def test_input_generator_is_stopped_at_budget():
    consumed = 0

    def facts():
        nonlocal consumed
        while True:
            consumed += 1
            yield Count("2026-09-30", 1, 1)

    with pytest.raises(MoneyflowContractError, match="history_date_fact_budget"):
        build("moneyflow_dc", facts(), cutoff="2026-09-30")
    assert consumed == 20001


@pytest.mark.parametrize(
    "cutoff", (None, "today", "20260930", "2026-09-31", "2026-09-30'; DROP")
)
def test_explicit_valid_cutoff_required(cutoff):
    with pytest.raises(MoneyflowContractError):
        build("moneyflow_dc", (Count("2026-09-30", 1, 1),), cutoff=cutoff)


def test_market_one_row_and_independent_schema_keys():
    with pytest.raises(MoneyflowContractError, match="history_market_count"):
        small("moneyflow_mkt_dc", 2)
    assert history_source_key_fields("moneyflow_ind_dc") == (
        "trade_date",
        "content_type",
        "name",
    )
    assert history_source_key_fields("moneyflow") == ("ts_code", "trade_date")
    assert history_source_key_fields("moneyflow_mkt_dc") == ("trade_date",)
    assert len({small(dataset).schema_hash for dataset in BASELINE}) == 7
    assert (
        next(
            c.type
            for c in history_schema("moneyflow", silver=True)
            if c.name == "trade_date"
        )
        == "DATE"
    )


@pytest.mark.parametrize(
    "field,value",
    (
        ("schema_hash", "0" * 64),
        ("source_counts_hash", "0" * 64),
        ("plan_hash", "0" * 64),
        ("windows", ()),
        ("source_units", ()),
        ("cutoff", "2026-10-08"),
        ("dataset", "moneyflow_ths"),
        ("date_counts", (Count("2026-09-30", 2, 2),)),
    ),
)
def test_plan_tampering_rejected(field, value):
    with pytest.raises(MoneyflowContractError, match="history_plan_changed"):
        sql(replace(small(), **{field: value}), 0)


@pytest.mark.parametrize("dataset", BASELINE)
def test_sql_readonly_fixed_projection_and_no_alias_sort(dataset):
    plan = small(dataset)
    statement = sql(plan, 0)
    assert statement.startswith(
        "BEGIN READ ONLY;\nSET LOCAL statement_timeout = '120s';"
    )
    assert statement.endswith("ROLLBACK;\n")
    assert statement.count(";") == 4
    assert f"FROM raw_tushare.{dataset} AS source" in statement
    assert (
        "TO STDOUT WITH (FORMAT CSV, HEADER TRUE, NULL E'\\\\N', ENCODING 'UTF8')"
        in statement
    )
    assert "LIMIT 100000" in statement
    assert (
        "ORDER BY "
        + ", ".join(f'source."{key}"' for key in history_source_key_fields(dataset))
        in statement
    )
    assert "to_char(source.\"trade_date\", 'YYYY-MM-DD')" in statement
    for c in history_schema(dataset):
        assert f'source."{c.name}"' in statement
    for forbidden in (
        "SELECT *",
        "OFFSET",
        "payload",
        "ingested_at",
        "INSERT",
        "DELETE",
        "UPDATE",
        "CREATE",
        "COMMIT",
        "PROGRAM",
        "tushare_token",
    ):
        assert forbidden not in statement


def test_keyset_first_continuation_and_closed_verification():
    plan = build(
        "moneyflow",
        (Count("2026-09-29", 60000, 60000), Count("2026-09-30", 50000, 50000)),
        cutoff="2026-09-30",
    )
    after, through = ("000001.SZ", "2026-09-29"), ("000002.SZ", "2026-09-30")
    assert "BETWEEN DATE '2026-09-29' AND DATE '2026-09-30'" in sql(plan, 0)
    assert "> (E'000001.SZ', DATE '2026-09-29')" in sql(plan, 1, after_key=after)
    assert "<= (E'000002.SZ', DATE '2026-09-30')" in sql(
        plan, 1, after_key=after, through_key=through
    )
    assert " <= " in sql(plan, 0, through_key=through)
    for unit, kwargs in (
        (1, {}),
        (0, {"after_key": after}),
        (1, {"after_key": through, "through_key": after}),
    ):
        with pytest.raises(MoneyflowContractError):
            sql(plan, unit, **kwargs)


@pytest.mark.parametrize(
    "key",
    (
        (),
        ("", "2026-09-30"),
        (None, "2026-09-30"),
        ("0" * 65, "2026-09-30"),
        ("A\x00", "2026-09-30"),
        ("A", "20260930"),
        ("A", "2026-10-01"),
        ["A", "2026-09-30"],
    ),
)
def test_invalid_keyset_boundary(key):
    with pytest.raises(MoneyflowContractError):
        sql(small("moneyflow"), 0, through_key=key)


def test_boundary_text_is_quoted_without_assuming_current_security_pool():
    statement = sql(
        small("moneyflow"), 0, through_key=("old\\code'; SELECT 1;--", "2026-09-30")
    )
    assert "E'old\\\\code''; SELECT 1;--'" in statement
    with pytest.raises(MoneyflowContractError, match="history_unexpected_keyset"):
        sql(small(), 0, through_key=("000001.SZ", "2026-09-30"))


@pytest.mark.parametrize("unit_id", (-1, 1, True, 0.0, "0"))
def test_unapproved_unit_id(unit_id):
    with pytest.raises(MoneyflowContractError):
        sql(small(), unit_id)


def test_planner_has_no_execution_or_active_definitions():
    import orchestrator.defs.bootstrap.moneyflow_history_plan as module

    tree = ast.parse(Path(module.__file__).read_text())
    imports = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]
    imports += [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not any(
        name.startswith(
            ("subprocess", "duckdb", "dagster", "os", "requests", "socket", "src.")
        )
        for name in imports
    )
    decorators = [
        decorator
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
    ]
    assert all(
        isinstance(decorator, ast.Name) and decorator.id == "property"
        for decorator in decorators
    )
