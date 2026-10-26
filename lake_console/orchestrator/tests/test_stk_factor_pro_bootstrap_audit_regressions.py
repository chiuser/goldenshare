"""Fourth-batch audit regressions, LLD 9/10.4/17; real temporary Parquet only.

Business carriers come from the shared doc328-based source fixture. Faults alter
only the reviewed record field or DROP call, never the actual source contract.
"""

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from shutil import copyfile
from zoneinfo import ZoneInfo

import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_publication as P
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as R
from orchestrator.defs.checks import stk_factor_pro as checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.stk_factor_pro_candidates import SILVER_EXPECTED
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    check_test_space,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection


def _setup(conn, tmp_path, *, rows=None, counts=None, day=None):
    options = {} if counts is None else {"counts": counts}
    lake, staging, approval, _ = approval_fixture(conn, tmp_path, **options)
    source = source_fixture(
        conn,
        staging_root=staging,
        approval=approval,
        rows=(native_row(),) if rows is None else rows,
        day=day,
    )
    return {
        "lake_root": lake,
        "staging_root": staging,
        "approval": approval,
        "source_complete": source,
        "before_publish": lambda: None,
    }


def _raw_only(conn, args, monkeypatch):
    def stop(*_args, **_kwargs):
        raise OSError("intentional stop after complete Raw")

    with monkeypatch.context() as scoped:
        scoped.setattr(P, "build_stk_factor_pro_silver_candidate", stop)
        with pytest.raises(OSError, match="intentional stop"):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
            )


def _silver_intent(conn, args):
    approval, source = args["approval"], args["source_complete"]
    staging, lake = args["staging_root"], args["lake_root"]
    root = R.operation_root(staging, approval)
    raw = P._target(lake, source.trade_date, "raw")
    candidate = R.operation_path(
        staging, approval, f"candidates/{source.trade_date}/silver/part-000.parquet"
    )
    P.build_stk_factor_pro_silver_candidate(
        conn,
        verified_raw_path=raw,
        target_trade_date=source.trade_date,
        candidate_path=candidate,
        run_root=root,
    )
    fragment = P._silver_fragment(
        conn, candidate, root, SILVER_EXPECTED, source.trade_date
    )
    conn.execute(f"DROP TABLE {SILVER_EXPECTED}")
    intent = C.StkFactorProBootstrapPublicationIntent(
        1,
        approval.operation_id,
        R.approval_sha(staging, approval),
        source.trade_date,
        "silver",
        source.source_complete_digest,
        checks.factor_file_sha(raw),
        "replace",
        None,
        fragment,
        fragment.file_sha256,
        "0" * 64,
        datetime.now(ZoneInfo("Asia/Shanghai")),
    )
    return replace(
        intent, intent_digest=C.stk_factor_pro_bootstrap_intent_digest(intent)
    )


@pytest.mark.parametrize("existing_intent", [False, True])
def test_silver_rejects_wrong_raw_binding_before_any_silver_publication(
    tmp_path, monkeypatch, existing_intent
):
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path)
        _raw_only(conn, args, monkeypatch)
        valid = _silver_intent(conn, args)
        wrong = replace(valid, raw_file_sha256="f" * 64)
        wrong = replace(
            wrong, intent_digest=C.stk_factor_pro_bootstrap_intent_digest(wrong)
        )
        if existing_intent:
            # Model an old, internally self-consistent erroneous intent written
            # before this guard existed. The canonical record writer alone is
            # intentionally not the publication authority.
            R.write_json(
                R.operation_path(
                    args["staging_root"],
                    args["approval"],
                    f"publication/{wrong.trade_date}/silver/intent.json",
                ),
                wrong,
            )
            with pytest.raises(ValueError, match="Raw完成事实"):
                P.publish_bootstrap_date(
                    conn,
                    **args,
                    check_space=check_test_space,
                )
        else:
            with pytest.raises(ValueError, match="Raw完成事实"):
                P.write_stk_factor_pro_bootstrap_publication_intent(
                    lake_root=args["lake_root"],
                    staging_root=args["staging_root"],
                    approval=args["approval"],
                    record=wrong,
                    check_space=check_test_space,
                )
        silver = P._target(args["lake_root"], wrong.trade_date, "silver")
        assert not silver.exists()
        assert not R.operation_path(
            args["staging_root"],
            args["approval"],
            f"publication/{wrong.trade_date}/silver/complete.json",
        ).exists()


def test_valid_silver_binding_and_equivalent_existing_raw_are_accepted(tmp_path):
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path, rows=(native_row(open=-1.25),))
        source = args["source_complete"]
        source_file = R.operation_path(
            args["staging_root"],
            args["approval"],
            source.fragments[0].fragment.relative_path,
        )
        target = P._target(args["lake_root"], source.trade_date, "raw")
        target.parent.mkdir(parents=True)
        copyfile(source_file, target)
        raw, silver = P.publish_bootstrap_date(
            conn,
            **args,
            check_space=check_test_space,
        )
        assert raw.passed and silver.passed
        raw_intent, _ = P.read_stk_factor_pro_bootstrap_publication(
            lake_root=args["lake_root"],
            staging_root=args["staging_root"],
            approval=args["approval"],
            trade_date=source.trade_date,
            layer="raw",
        )
        silver_intent, _ = P.read_stk_factor_pro_bootstrap_publication(
            lake_root=args["lake_root"],
            staging_root=args["staging_root"],
            approval=args["approval"],
            trade_date=source.trade_date,
            layer="silver",
        )
        assert raw_intent.mode == "reuse"
        assert silver_intent.raw_file_sha256 == raw.file_sha256
        assert conn.execute(
            "SELECT open FROM read_parquet(?)", [str(silver.path)]
        ).fetchone() == (-1.25,)


def test_empty_source_requires_same_operation_but_valid_empty_has_no_files(tmp_path):
    day = date(2019, 10, 16)
    with connection(tmp_path) as conn:
        args = _setup(
            conn,
            tmp_path,
            rows=(),
            day=day,
            counts=((date(2019, 10, 15), 1), (day, 0)),
        )
        wrong = replace(args["source_complete"], operation_id="other-operation")
        wrong = replace(
            wrong,
            source_complete_digest=C.stk_factor_pro_bootstrap_source_complete_digest(
                wrong
            ),
        )
        with pytest.raises(ValueError, match="本operation"):
            P.publish_bootstrap_date(
                conn,
                **{**args, "source_complete": wrong},
                check_space=check_test_space,
            )
        assert P.publish_bootstrap_date(
            conn,
            **args,
            check_space=check_test_space,
        ) == (None, None)
        assert not P._target(args["lake_root"], day, "raw").exists()
        assert not P._target(args["lake_root"], day, "silver").exists()


@pytest.mark.parametrize("absolute", [False, True])
def test_diagnostics_are_saved_as_operation_relative_path(
    tmp_path, monkeypatch, absolute
):
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path)
        relative = Path("diagnostics/verified-result.json")
        root = R.operation_root(args["staging_root"], args["approval"])
        diagnostic = root / relative
        diagnostic.parent.mkdir(parents=True)
        diagnostic.write_text('{"verified":true}\n')
        original = P.write_stk_factor_pro_bootstrap_publication_complete

        def attach(**kwargs):
            record = kwargs["record"]
            if record.layer == "raw":
                record = replace(
                    record,
                    audit=replace(
                        record.audit,
                        diagnostics_path=diagnostic if absolute else relative,
                    ),
                )
            return original(**{**kwargs, "record": record})

        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", attach
        )
        raw, silver = P.publish_bootstrap_date(
            conn,
            **args,
            check_space=check_test_space,
        )
        assert raw.passed and silver.passed
        _, saved = P.read_stk_factor_pro_bootstrap_publication(
            lake_root=args["lake_root"],
            staging_root=args["staging_root"],
            approval=args["approval"],
            trade_date=args["source_complete"].trade_date,
            layer="raw",
        )
        assert saved.audit.diagnostics_path == relative
        assert not saved.audit.diagnostics_path.is_absolute()
        record_path = R.operation_path(
            args["staging_root"],
            args["approval"],
            f"publication/{saved.trade_date}/raw/complete.json",
        )
        assert (
            '"diagnostics_path":"diagnostics/verified-result.json"'
            in record_path.read_text()
        )


@pytest.mark.parametrize(
    "outside",
    [Path("../outside.json"), Path("/private/tmp/other-operation/diagnostic.json")],
)
def test_diagnostics_cannot_leave_approved_operation(tmp_path, monkeypatch, outside):
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path)
        original = P.write_stk_factor_pro_bootstrap_publication_complete

        def attach(**kwargs):
            record = kwargs["record"]
            return original(
                **{
                    **kwargs,
                    "record": replace(
                        record, audit=replace(record.audit, diagnostics_path=outside)
                    ),
                }
            )

        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", attach
        )
        with pytest.raises(ValueError):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
            )
        assert not R.operation_path(
            args["staging_root"],
            args["approval"],
            f"publication/{args['source_complete'].trade_date}/raw/complete.json",
        ).exists()


@pytest.mark.parametrize("field", ["content", "rows"])
def test_complete_rejects_audit_consistent_but_wrong_intent_content_or_rows(
    tmp_path, monkeypatch, field
):
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path)
        original = P.write_stk_factor_pro_bootstrap_publication_complete

        def wrong_fact(**kwargs):
            record = kwargs["record"]
            if field == "content":
                record = replace(record, content_sha256="f" * 64)
            else:
                # Keep the complete model and its audit internally consistent;
                # the production guard must bind them to the real intent.
                comparison = replace(
                    record.audit.comparison, expected_rows=2, actual_rows=2
                )
                audit = replace(record.audit, row_count=2, comparison=comparison)
                record = replace(record, actual_rows=2, audit=audit)
            return original(**{**kwargs, "record": record})

        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", wrong_fact
        )
        with pytest.raises(ValueError, match="完成记录与意图"):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
            )
        assert not R.operation_path(
            args["staging_root"],
            args["approval"],
            f"publication/{args['source_complete'].trade_date}/raw/complete.json",
        ).exists()


class _DropFailure:
    def __init__(self, conn, error):
        self.conn, self.error = conn, error
        self.drops = 0

    def execute(self, sql, *args, **kwargs):
        if sql == "DROP VIEW IF EXISTS stk_factor_pro_checked_file":
            self.drops += 1
            if self.error is not None:
                raise self.error
        return self.conn.execute(sql, *args, **kwargs)


@pytest.mark.parametrize(
    ("body_fails", "cleanup_fails"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_shared_check_cleanup_preserves_real_body_error_and_reports_cleanup(
    tmp_path, monkeypatch, body_fails, cleanup_fails
):
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path)
        source = args["source_complete"]
        path = R.operation_path(
            args["staging_root"],
            args["approval"],
            source.fragments[0].fragment.relative_path,
        )
        conn.execute(
            f"CREATE TEMP VIEW audit_expected AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        )
        if body_fails:
            path = tmp_path / "missing-fields.parquet"
            conn.execute(
                copy_query_to_parquet("SELECT ts_code FROM audit_expected", path)
            )
        cleanup_error = (
            OSError("injected DROP cleanup failure") if cleanup_fails else None
        )
        proxy = _DropFailure(conn, cleanup_error)
        observed = []
        real_require = checks.require_factor_relation

        def observe(*args, **kwargs):
            try:
                return real_require(*args, **kwargs)
            except ValueError as error:
                observed.append(error)
                raise

        monkeypatch.setattr(checks, "require_factor_relation", observe)

        def run():
            return checks.audit_stk_factor_pro_file(
                proxy,
                path=path,
                expected_relation="audit_expected",
                target_trade_date=source.trade_date,
                layer="raw",
            )

        if body_fails:
            with pytest.raises(ValueError) as result:
                run()
            assert observed and result.value is observed[0]
            if cleanup_fails:
                assert any("OSError" in note for note in result.value.__notes__)
        elif cleanup_fails:
            with pytest.raises(OSError) as result:
                run()
            assert result.value is cleanup_error
        else:
            audit = run()
            assert audit.passed and audit.row_count == 1
        assert proxy.drops == 1
        if not cleanup_fails:
            assert (
                conn.execute(
                    "SELECT count(*) FROM duckdb_views() WHERE view_name='stk_factor_pro_checked_file'"
                ).fetchone()[0]
                == 0
            )
