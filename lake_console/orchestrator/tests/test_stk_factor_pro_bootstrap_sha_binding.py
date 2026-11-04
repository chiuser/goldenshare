"""LLD 17.8.1: original audit identity authorizes each bootstrap file.

The producer is the existing doc328-based native fixture, with literal close=10.
Candidate and equivalent existing-file checks use independent literal values;
newly written records inherit the first audit and actual target byte identity.
"""

from dataclasses import replace

import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_publication as P
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import operation_path
from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.io.stk_factor_pro_candidates import BOOTSTRAP_DAY_SOURCE
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    bootstrap_date_results,
    check_test_space,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_bootstrap_publication import restore_source_context


def _setup(conn, tmp_path, *, known_records):
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
        "source_relation": BOOTSTRAP_DAY_SOURCE,
        "before_publish": lambda: None,
    }


def _paths(args, layer):
    day = args["source_complete"].trade_date
    candidate = operation_path(
        args["staging_root"],
        args["approval"],
        f"candidates/{day}/{layer}/part-000.parquet",
    )
    intent = operation_path(
        args["staging_root"],
        args["approval"],
        f"publication/{day}/{layer}/intent.json",
    )
    return candidate, intent, P._target(args["lake_root"], day, layer)


def _spy_promotions(monkeypatch, target):
    actual = P.atomic_promote
    promotions = []

    def promote(candidate, destination, **kwargs):
        if destination == target:
            promotions.append((candidate, destination))
        return actual(candidate, destination, **kwargs)

    monkeypatch.setattr(P, "atomic_promote", promote)
    return promotions


def _equivalent_target_on_build(conn, args, layer, monkeypatch):
    name = (
        "build_stk_factor_pro_raw_candidate_from_relation"
        if layer == "raw"
        else "build_stk_factor_pro_silver_candidate"
    )
    original = getattr(P, name)
    candidate, _, target = _paths(args, layer)

    def build(*values, **keywords):
        audit = original(*values, **keywords)
        target.parent.mkdir(parents=True, exist_ok=True)
        conn.execute(
            "CREATE TEMP TABLE sha_binding_existing_target AS "
            "SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(candidate)],
        )
        try:
            conn.execute(
                "COPY sha_binding_existing_target TO ? "
                "(FORMAT PARQUET, COMPRESSION UNCOMPRESSED)",
                [str(target)],
            )
        finally:
            conn.execute("DROP TABLE sha_binding_existing_target")
        assert factor_file_sha(candidate) != factor_file_sha(target)
        return audit

    monkeypatch.setattr(P, name, build)
    return candidate, target


@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_equivalent_target_different_bytes_uses_original_target_audit(
    tmp_path, monkeypatch, layer
):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path, known_records=known_records)
        candidate, target = _equivalent_target_on_build(conn, args, layer, monkeypatch)
        promotions = _spy_promotions(monkeypatch, target)
        raw, silver = P.publish_bootstrap_date(
            conn,
            **args,
            check_space=check_test_space,
            known_records=known_records,
            date_results=bootstrap_date_results(date_results, args["source_complete"]),
        )
        audit = raw if layer == "raw" else silver
        assert audit.passed and promotions == []
        intent, complete = P.read_stk_factor_pro_bootstrap_publication(
            **{key: args[key] for key in ("lake_root", "staging_root", "approval")},
            trade_date=args["source_complete"].trade_date,
            layer=layer,
            known_records=known_records,
        )
        assert intent.mode == "reuse"
        assert intent.expected_file_sha256 == intent.prior_file_sha256
        assert intent.expected_file_sha256 == complete.actual_file_sha256
        assert intent.expected_file_sha256 == factor_file_sha(target)
        assert intent.candidate.file_sha256 == factor_file_sha(candidate)
        assert intent.expected_file_sha256 != intent.candidate.file_sha256


@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_wrong_audit_identity_is_not_publication_authority(
    tmp_path, monkeypatch, layer
):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path, known_records=known_records)
        _, _, target = _paths(args, layer)
        name = (
            "build_stk_factor_pro_raw_candidate_from_relation"
            if layer == "raw"
            else "build_stk_factor_pro_silver_candidate"
        )
        original = getattr(P, name)

        def build(*values, **keywords):
            audit = original(*values, **keywords)
            return replace(audit, path=audit.path.with_name("different.parquet"))

        monkeypatch.setattr(P, name, build)
        with pytest.raises(ValueError, match="未通过完整业务对账"):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
                known_records=known_records,
                date_results=bootstrap_date_results(
                    date_results, args["source_complete"]
                ),
            )
        assert not target.exists()


@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_recovery_accepts_expected_target_with_candidate_already_moved(
    tmp_path, monkeypatch, layer
):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path, known_records=known_records)
        candidate, intent_path, target = _paths(args, layer)
        original = P.write_stk_factor_pro_bootstrap_publication_complete

        def fail_complete(**keywords):
            if keywords["record"].layer == layer:
                raise OSError("completed replace before checkpoint")
            return original(**keywords)

        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", fail_complete
        )
        with pytest.raises(OSError, match="before checkpoint"):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
                known_records=known_records,
                date_results=bootstrap_date_results(
                    date_results, args["source_complete"]
                ),
            )
        assert target.is_file() and not candidate.exists()
        target_sha = factor_file_sha(target)
        intent_bytes = intent_path.read_bytes()
        promotions = _spy_promotions(monkeypatch, target)
        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", original
        )
        known_records, date_results, args = restore_source_context(conn, args)
        assert all(
            audit.passed
            for audit in P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
                known_records=known_records,
                date_results=bootstrap_date_results(
                    date_results, args["source_complete"]
                ),
            )
        )
        assert factor_file_sha(target) == target_sha
        assert intent_path.read_bytes() == intent_bytes
        assert promotions == [] and not candidate.exists()
