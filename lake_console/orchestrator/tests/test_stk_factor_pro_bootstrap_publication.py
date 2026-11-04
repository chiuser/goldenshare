"""Real temporary Parquet/atomic replacement, with independent business values."""

from collections import Counter

import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_publication as P
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as records
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import operation_path
from orchestrator.defs.checks.stk_factor_pro import (
    factor_file_sha,
    release_stk_factor_pro_audit_relations,
)
from orchestrator.defs.io import stk_factor_pro_candidates as candidates
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    bootstrap_date_results,
    check_test_space,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection


def setup(conn, tmp_path, *, known_records, date_results):
    lake, staging, approval, _ = approval_fixture(
        conn, tmp_path, known_records=known_records
    )
    source = source_fixture(
        conn,
        staging_root=staging,
        approval=approval,
        rows=(native_row(),),
        known_records=known_records,
    )
    return {
        "lake_root": lake,
        "staging_root": staging,
        "approval": approval,
        "source_complete": source,
        "source_record_sha256": known_records[
            operation_path(
                staging,
                approval,
                f"source/dates/{source.trade_date}/source-complete.json",
            )
        ][1],
        "source_relation": candidates.BOOTSTRAP_DAY_SOURCE,
        "before_publish": lambda: None,
    }


def release_date_work(conn, *, include_source=False):
    """Direct tests own the same date scope as the real process callback."""
    tables = (
        candidates.SILVER_EXPECTED,
        candidates.RAW_EXPECTED,
        candidates.RAW_MATCHED_KEYS,
        candidates.DAY_PRIOR,
    ) + ((candidates.BOOTSTRAP_DAY_SOURCE,) if include_source else ())
    with records.resource_cleanup(
        *(
            lambda name=name: conn.execute(f"DROP TABLE IF EXISTS {name}")
            for name in tables
        ),
        lambda: release_stk_factor_pro_audit_relations(conn),
    ):
        pass


def restore_source_context(conn, args):
    """A fresh test invocation loads its persisted source through real readers."""
    release_date_work(conn, include_source=True)
    known_records = {}
    source = records.read_stk_factor_pro_bootstrap_source_complete(
        conn,
        staging_root=args["staging_root"],
        approval=args["approval"],
        trade_date=args["source_complete"].trade_date,
        known_records=known_records,
    )
    month = next(
        item
        for item in args["approval"].month_limits
        if item.month_start == source.month_start
    )
    verification = records.BootstrapFragmentVerification(
        conn,
        staging_root=args["staging_root"],
        approval=args["approval"],
        month=month,
        known_records=known_records,
    )
    with records.resource_cleanup(verification.close):
        relation = records.load_complete_source(
            conn,
            staging_root=args["staging_root"],
            approval=args["approval"],
            record=source,
            verification=verification,
            known_records=known_records,
        )
    path = operation_path(
        args["staging_root"],
        args["approval"],
        f"source/dates/{source.trade_date}/source-complete.json",
    )
    return (
        known_records,
        bootstrap_date_results({}, source),
        {
            **args,
            "source_complete": source,
            "source_record_sha256": known_records[path][1],
            "source_relation": relation,
        },
    )


def test_full_two_layer_publication_and_repeat_zero_source_reads(tmp_path, monkeypatch):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        raw, silver = P.publish_bootstrap_date(
            conn,
            **args,
            check_space=check_test_space,
            known_records=known_records,
            date_results=bootstrap_date_results(date_results, args["source_complete"]),
        )
        assert raw.passed and silver.passed and raw.row_count == silver.row_count == 1
        assert conn.execute(
            "SELECT ts_code,trade_date,open,close FROM read_parquet(?)",
            [str(silver.path)],
        ).fetchone() == ("000001.SZ", args["source_complete"].trade_date, 1.25, 10.0)
        monkeypatch.setattr(
            records,
            "load_complete_source",
            lambda *_a, **_k: pytest.fail("complete date source must not be rescanned"),
        )
        assert P.publish_bootstrap_date(
            conn,
            **args,
            check_space=check_test_space,
            known_records=known_records,
            date_results=bootstrap_date_results(date_results, args["source_complete"]),
        ) == (raw, silver)
        monkeypatch.undo()
        known_records, date_results, args = restore_source_context(conn, args)
        bound = Counter()
        intent_identity, complete_identity = P._intent_identity, P._complete_identity

        def first_intent(**kwargs):
            bound[(kwargs["layer"], "intent")] += 1
            return intent_identity(**kwargs)

        def first_complete(**kwargs):
            bound[(kwargs["layer"], "complete")] += 1
            return complete_identity(**kwargs)

        monkeypatch.setattr(P, "_intent_identity", first_intent)
        monkeypatch.setattr(P, "_complete_identity", first_complete)
        for _ in range(2):
            assert P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
                known_records=known_records,
                date_results=date_results,
            ) == (raw, silver)
        assert bound == {
            ("raw", "intent"): 1,
            ("raw", "complete"): 1,
            ("silver", "intent"): 1,
            ("silver", "complete"): 1,
        }
        # Publication hands verified relations to its caller; process owns the
        # date scope and source owns DAY. This direct test is that caller.
        release_date_work(conn, include_source=True)
        assert (
            conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE temporary AND table_name LIKE 'stk_factor_pro_%'"
            ).fetchall()
            == []
        )


def test_raw_completed_silver_failure_then_same_operation_continues(
    tmp_path, monkeypatch
):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        original = P.build_stk_factor_pro_silver_candidate

        def fail(*_a, **_k):
            raise OSError("silver failure")

        monkeypatch.setattr(P, "build_stk_factor_pro_silver_candidate", fail)
        with pytest.raises(OSError, match="silver failure"):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
                known_records=known_records,
                date_results=bootstrap_date_results(
                    date_results, args["source_complete"]
                ),
            )
        monkeypatch.setattr(P, "build_stk_factor_pro_silver_candidate", original)
        release_date_work(conn)
        monkeypatch.setattr(
            records,
            "load_complete_source",
            lambda *_a, **_k: pytest.fail("Raw complete must be reused"),
        )
        raw, silver = P.publish_bootstrap_date(
            conn,
            **args,
            check_space=check_test_space,
            known_records=known_records,
            date_results=bootstrap_date_results(date_results, args["source_complete"]),
        )
        assert raw.passed and silver.passed


def test_replace_completed_but_record_write_failed_can_recover(tmp_path, monkeypatch):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        original = P.write_stk_factor_pro_bootstrap_publication_complete

        def fail(**kwargs):
            if kwargs["record"].layer == "raw":
                raise OSError("checkpoint failure")
            return original(**kwargs)

        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", fail
        )
        with pytest.raises(OSError, match="checkpoint"):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
                known_records=known_records,
                date_results=bootstrap_date_results(
                    date_results, args["source_complete"]
                ),
            )
        assert not operation_path(
            args["staging_root"],
            args["approval"],
            "candidates/2019-10-16/raw/part-000.parquet",
        ).exists()
        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", original
        )
        known_records, date_results, args = restore_source_context(conn, args)
        assert all(
            a.passed
            for a in P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
                known_records=known_records,
                date_results=bootstrap_date_results(
                    date_results, args["source_complete"]
                ),
            )
        )


def test_changed_complete_target_never_overwritten(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        raw, _ = P.publish_bootstrap_date(
            conn,
            **args,
            check_space=check_test_space,
            known_records=known_records,
            date_results=bootstrap_date_results(date_results, args["source_complete"]),
        )
        raw.path.write_bytes(b"external modification")
        before = factor_file_sha(raw.path)
        with pytest.raises(ValueError, match="改变"):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
                known_records=known_records,
                date_results=bootstrap_date_results(
                    date_results, args["source_complete"]
                ),
            )
        assert factor_file_sha(raw.path) == before


def test_existing_different_target_stops_before_replace(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        target = P._target(args["lake_root"], args["source_complete"].trade_date, "raw")
        target.parent.mkdir(parents=True)
        source_path = operation_path(
            args["staging_root"],
            args["approval"],
            args["source_complete"].fragments[0].fragment.relative_path,
        )
        from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet

        conn.execute(
            copy_query_to_parquet(
                f"SELECT * REPLACE (99.0::DOUBLE AS close) FROM {read_parquet(source_path, hive_partitioning=False)}",
                target,
            )
        )
        before = factor_file_sha(target)
        with pytest.raises(ValueError, match="内容不同"):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
                known_records=known_records,
                date_results=bootstrap_date_results(
                    date_results, args["source_complete"]
                ),
            )
        assert factor_file_sha(target) == before


def test_normal_publication_inherits_the_two_candidate_audits(tmp_path, monkeypatch):
    known_records, date_results = {}, {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        audited = []
        digests = Counter()
        original = candidates.audit_stk_factor_pro_file
        original_sha = P.factor_file_sha
        original_digest = P.C.stk_factor_pro_bootstrap_intent_digest

        def one_digest(record):
            digests[record.layer] += 1
            return original_digest(record)

        class NoSourceRead:
            def __getattr__(self, key):
                return getattr(conn, key)

            def execute(self, query, parameters=None):
                if "read_parquet" in str(query).lower():
                    assert "source/month=" not in str(query) + repr(parameters)
                return (
                    conn.execute(query)
                    if parameters is None
                    else conn.execute(query, parameters)
                )

        def no_source_sha(path):
            assert "source/month=" not in str(path)
            return original_sha(path)

        def observe(connection, **kwargs):
            audited.append(kwargs["path"])
            return original(connection, **kwargs)

        monkeypatch.setattr(candidates, "audit_stk_factor_pro_file", observe)
        monkeypatch.setattr(P, "audit_stk_factor_pro_file", observe)
        monkeypatch.setattr(P, "factor_file_sha", no_source_sha)
        monkeypatch.setattr(P.C, "stk_factor_pro_bootstrap_intent_digest", one_digest)
        raw, silver = P.publish_bootstrap_date(
            NoSourceRead(),
            **args,
            check_space=check_test_space,
            known_records=known_records,
            date_results=bootstrap_date_results(date_results, args["source_complete"]),
        )
        root = operation_path(args["staging_root"], args["approval"], "candidates")
        assert audited == [
            root / "2019-10-16/raw/part-000.parquet",
            root / "2019-10-16/silver/part-000.parquet",
        ]
        for layer in ("raw", "silver"):
            P.read_stk_factor_pro_bootstrap_publication(
                **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
                trade_date=args["source_complete"].trade_date,
                layer=layer,
                known_records=known_records,
            )
        assert digests == {"raw": 1, "silver": 1}
        entry = date_results[args["source_complete"].trade_date]
        source_path = operation_path(
            args["staging_root"],
            args["approval"],
            "source/dates/2019-10-16/source-complete.json",
        )
        assert entry["source_record_sha256"] == known_records[source_path][1]
        assert "source_complete_digest" not in entry
        assert (
            entry["source_complete"].source_complete_digest
            == args["source_complete"].source_complete_digest
        )
        assert entry["raw_audit"] is raw and entry["silver_audit"] is silver
        assert entry["replaced_layers"] == {"raw", "silver"}
        assert entry["import_complete"] is True


def test_replace_fact_exists_before_missing_complete_record(tmp_path, monkeypatch):
    known_records, date_results = {}, {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )

        def fail(**kwargs):
            raise OSError("complete write failed")

        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", fail
        )
        with pytest.raises(OSError, match="complete write failed"):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
                known_records=known_records,
                date_results=bootstrap_date_results(
                    date_results, args["source_complete"]
                ),
            )
        entry = date_results[args["source_complete"].trade_date]
        raw = entry["raw_audit"]
        assert raw.path.is_file() and raw.passed
        assert known_records[raw.path][0] is raw
        assert entry["replaced_layers"] == {"raw"}
        assert entry["raw_complete"] is None and entry["import_complete"] is False


def test_complete_fact_registered_before_its_post_save_failure(tmp_path):
    known_records, date_results = {}, {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )

        def fail_after_complete(stage, **facts):
            if (
                facts.get("event") == "record_saved"
                and facts["path"].name == "complete.json"
            ):
                raise OSError("post-complete capacity")
            return check_test_space(stage, **facts)

        with pytest.raises(OSError, match="post-complete capacity"):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=fail_after_complete,
                known_records=known_records,
                date_results=bootstrap_date_results(
                    date_results, args["source_complete"]
                ),
            )
        entry = date_results[args["source_complete"].trade_date]
        complete_path = operation_path(
            args["staging_root"],
            args["approval"],
            "publication/2019-10-16/raw/complete.json",
        )
        assert entry["raw_complete"] is known_records[complete_path][0]
        assert entry["raw_audit"].path.is_file()
        assert entry["silver_complete"] is None and entry["import_complete"] is False
