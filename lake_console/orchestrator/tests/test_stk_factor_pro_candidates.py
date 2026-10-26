from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from orchestrator.defs.io.stk_factor_pro_candidates import (
    build_stk_factor_pro_raw_batch,
    build_stk_factor_pro_raw_candidate,
    build_stk_factor_pro_silver_candidate,
    release_stk_factor_pro_day_source,
    stk_factor_pro_double,
    stk_factor_pro_raw_trade_date,
)
from orchestrator.defs.io.stk_factor_pro_download import (
    verify_stk_factor_pro_day_source,
)
from tests.stk_factor_pro_test_support import (
    NAMES,
    connection,
    contract,
    identity,
    result,
    row,
    summary,
)


@pytest.mark.parametrize("layer", ["raw", "silver"])
@pytest.mark.parametrize(
    "kind",
    [
        "live_parent_link",
        "dangling_parent_link",
        "live_file_link",
        "dangling_file_link",
        "other_run",
        "relative",
        "parent_traversal",
        "existing_candidate",
        "candidate_directory",
    ],
)
def test_candidate_builders_reject_bad_paths_before_sql_or_write(tmp_path, layer, kind):
    # Independent forbidden layouts from LLD 15.9. The real native source is
    # prepared first; only SQL after the builder call is forbidden by this probe.
    run_root, outside = tmp_path / "run-a", tmp_path / "outside"
    run_root.mkdir()
    candidate = run_root / "candidates" / "day" / layer / "data.parquet"
    if kind.endswith("parent_link"):
        candidate.parent.parent.mkdir(parents=True)
        if kind == "live_parent_link":
            outside.mkdir()
        candidate.parent.symlink_to(outside, target_is_directory=True)
    elif kind.endswith("file_link"):
        outside.mkdir()
        external_file = outside / "data.parquet"
        if kind == "live_file_link":
            external_file.write_bytes(b"existing external file")
        candidate.parent.mkdir(parents=True)
        candidate.symlink_to(external_file)
    elif kind == "other_run":
        candidate = (
            tmp_path / "other-run" / "candidates" / "day" / layer / "data.parquet"
        )
    elif kind == "relative":
        candidate = Path("relative") / "data.parquet"
    elif kind == "parent_traversal":
        candidate = run_root / "candidates" / ".." / "outside" / "data.parquet"
    elif kind == "existing_candidate":
        candidate.parent.mkdir(parents=True)
        candidate.write_bytes(b"old candidate must not be reused or overwritten")
    elif kind == "candidate_directory":
        candidate = run_root / "candidates"

    class NoSQL:
        calls = 0

        def execute(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("invalid candidate path reached SQL")

    with connection(tmp_path) as conn:
        source = verify_stk_factor_pro_day_source(
            conn,
            identity=identity(),
            result=result((row(),)),
            summary=summary(1),
            contract=contract(),
        )
        before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
        probe = NoSQL()
        try:
            with pytest.raises(ValueError, match="路径|候选"):
                if layer == "raw":
                    build_stk_factor_pro_raw_candidate(
                        probe,
                        source=source,
                        prior_path=None,
                        candidate_path=candidate,
                        run_root=run_root,
                    )
                else:
                    build_stk_factor_pro_silver_candidate(
                        probe,
                        verified_raw_path=tmp_path / "must-not-read.parquet",
                        target_trade_date=date(2026, 10, 16),
                        candidate_path=candidate,
                        run_root=run_root,
                    )
            assert probe.calls == 0
            assert (
                sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
                == before
            )
            if kind == "live_file_link":
                assert external_file.read_bytes() == b"existing external file"
            if kind == "existing_candidate":
                assert (
                    candidate.read_bytes()
                    == b"old candidate must not be reused or overwritten"
                )
        finally:
            release_stk_factor_pro_day_source(conn)


@pytest.mark.parametrize(
    "value",
    [
        True,
        "1",
        1.0,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1e9999"),
        Decimal("1e-9999"),
    ],
)
def test_http_invalid_numbers_rejected(value):
    with pytest.raises(ValueError):
        stk_factor_pro_double(value, source="http")


@pytest.mark.parametrize("value", [None, 0, -1, Decimal("-1.25"), Decimal("1e-300")])
def test_http_valid_numbers_preserved(value):
    assert stk_factor_pro_double(value, source="http") == (
        None if value is None else float(value)
    )


@pytest.mark.parametrize(
    "value", [True, 1, Decimal(1), "1", float("nan"), float("inf")]
)
def test_prod_invalid_numbers_rejected(value):
    with pytest.raises(ValueError):
        stk_factor_pro_double(value, source="prod_postgres")


def test_prod_date_and_finite_float_rule():
    assert (
        stk_factor_pro_raw_trade_date(date(2026, 10, 16), source="prod_postgres")
        == "20261016"
    )
    assert stk_factor_pro_double(-1.25, source="prod_postgres") == -1.25
    with pytest.raises(ValueError):
        stk_factor_pro_raw_trade_date(
            datetime(2026, 10, 16, tzinfo=UTC), source="prod_postgres"
        )


@pytest.mark.parametrize(
    "value", [None, 20261016, "2026-10-16", "20260230", "20261016 ", "２０２６１０１６"]
)
def test_invalid_source_date_rejected(value):
    with pytest.raises((ValueError, TypeError)):
        stk_factor_pro_raw_trade_date(value, source="http")


def test_per_record_field_reordering_and_independent_u(tmp_path):
    original = result((row(), row("600000.SH", close=Decimal(20))))
    reversed_record = replace(
        original.records[1],
        fields=tuple(reversed(NAMES)),
        values=tuple(reversed(original.records[1].values)),
    )
    reordered = replace(
        original,
        records=(original.records[0], reversed_record),
        observed_field_sets=(NAMES, tuple(reversed(NAMES))),
    )
    with connection(tmp_path) as conn:
        source = verify_stk_factor_pro_day_source(
            conn,
            identity=identity(),
            result=reordered,
            summary=summary(2),
            contract=contract(),
        )
        assert source.unit_result is reordered
        assert conn.execute(
            "SELECT ts_code,open,close,macd_bfq,pe FROM stk_factor_pro_day_source ORDER BY ts_code"
        ).fetchall() == [
            ("000001.SZ", 1.25, 10.0, -1.25, None),
            ("600000.SH", 1.25, 20.0, -1.25, None),
        ]
        assert "stk_factor_pro_current_batch" not in {
            r[0] for r in conn.execute("SHOW TABLES").fetchall()
        }
        release_stk_factor_pro_day_source(conn)
        assert conn.execute("SHOW TABLES").fetchall() == []


@pytest.mark.parametrize(
    "kind", ["missing", "extra", "duplicate", "width", "date", "key", "duplicate_key"]
)
def test_invalid_unit_input_rejected_without_u_leak(tmp_path, kind):
    original = result((row(),))
    rec = original.records[0]
    if kind == "missing":
        rec = replace(rec, fields=NAMES[:-1], values=rec.values[:-1])
    elif kind == "extra":
        rec = replace(rec, fields=(*NAMES, "extra"), values=(*rec.values, 0))
    elif kind == "duplicate":
        rec = replace(rec, fields=(*NAMES[:-1], NAMES[0]))
    elif kind == "width":
        rec = replace(rec, values=rec.values[:-1])
    elif kind == "date":
        rec = replace(rec, values=row(day="20261015"))
    elif kind == "key":
        rec = replace(rec, values=row(code=" 000001.SZ"))
    records = (rec, rec) if kind == "duplicate_key" else (rec,)
    value = replace(
        original,
        records=records,
        observed_field_sets=(rec.fields,),
        statistics=replace(original.statistics, row_count=len(records)),
    )
    with connection(tmp_path) as conn:
        with pytest.raises(ValueError):
            verify_stk_factor_pro_day_source(
                conn,
                identity=identity(),
                result=value,
                summary=summary(len(records)),
                contract=contract(),
            )
        assert conn.execute("SHOW TABLES").fetchall() == []


def test_batch_uses_nullable_float_columns_and_no_type_guessing():
    frame = build_stk_factor_pro_raw_batch(
        rows=(row(),),
        source_fields=NAMES,
        source="http",
        expected_dates=(date(2026, 10, 16),),
    )
    assert str(frame.pe.dtype) == "Float64" and frame.pe.isna().all()
    assert tuple(frame.columns) == NAMES


def test_conversion_error_identifies_stock_date_field_without_dumping_row():
    with pytest.raises(ValueError, match="000001.SZ/20261016字段close转换失败"):
        build_stk_factor_pro_raw_batch(
            rows=(row(close="invalid-number"),),
            source_fields=NAMES,
            source="http",
            expected_dates=(date(2026, 10, 16),),
        )
