"""LLD 17.8.1: original audit identity authorizes each bootstrap file.

The producer is the existing doc328-based native fixture, with literal close=10.
Faults rewrite a real temporary 261-column Parquet to close=99 after validation;
the expected refusal and value preservation are independent of the writer.
"""

from dataclasses import replace

import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_publication as P
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import operation_path
from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    check_test_space,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection


def _setup(conn, tmp_path):
    lake, staging, approval, _ = approval_fixture(conn, tmp_path)
    source = source_fixture(
        conn, staging_root=staging, approval=approval, rows=(native_row(),)
    )
    return {
        "lake_root": lake,
        "staging_root": staging,
        "approval": approval,
        "source_complete": source,
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


def _rewrite(conn, path, *, close=99.0):
    # A real changed file, not a fabricated SHA/audit return value.
    conn.execute(
        "CREATE OR REPLACE TEMP TABLE sha_binding_rewrite AS "
        "SELECT * REPLACE (?::DOUBLE AS close) "
        "FROM read_parquet(?,hive_partitioning=false)",
        [close, str(path)],
    )
    try:
        conn.execute(
            "COPY sha_binding_rewrite TO ? (FORMAT PARQUET, COMPRESSION UNCOMPRESSED)",
            [str(path)],
        )
    finally:
        conn.execute("DROP TABLE sha_binding_rewrite")


def _spy_promotions(monkeypatch, target):
    actual = P.atomic_promote
    promotions = []

    def promote(candidate, destination):
        if destination == target:
            promotions.append((candidate, destination))
        return actual(candidate, destination)

    monkeypatch.setattr(P, "atomic_promote", promote)
    return promotions


@pytest.mark.parametrize("layer", ["raw", "silver"])
@pytest.mark.parametrize("when", ["after_audit", "before_intent", "before_promotion"])
def test_changed_candidate_refused_before_formal_replace(
    tmp_path, monkeypatch, layer, when
):
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path)
        candidate, intent, target = _paths(args, layer)
        promotions = _spy_promotions(monkeypatch, target)
        changed = False
        if when == "after_audit":
            name = (
                "build_stk_factor_pro_raw_candidate_from_relation"
                if layer == "raw"
                else "build_stk_factor_pro_silver_candidate"
            )
            original = getattr(P, name)

            def build(*values, **keywords):
                nonlocal changed
                audit = original(*values, **keywords)
                _rewrite(conn, audit.path)
                changed = True
                return audit

            monkeypatch.setattr(P, name, build)
        else:

            def before_publish():
                nonlocal changed
                at_boundary = intent.exists() == (when == "before_promotion")
                if candidate.exists() and at_boundary and not changed:
                    _rewrite(conn, candidate)
                    changed = True

            args["before_publish"] = before_publish

        with pytest.raises(ValueError):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
            )
        assert changed
        assert promotions == []
        assert not target.exists()
        if layer == "silver":
            raw = P._target(
                args["lake_root"], args["source_complete"].trade_date, "raw"
            )
            assert conn.execute(
                "SELECT close FROM read_parquet(?,hive_partitioning=false)", [str(raw)]
            ).fetchone() == (10.0,)


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
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path)
        candidate, target = _equivalent_target_on_build(conn, args, layer, monkeypatch)
        promotions = _spy_promotions(monkeypatch, target)
        raw, silver = P.publish_bootstrap_date(
            conn,
            **args,
            check_space=check_test_space,
        )
        audit = raw if layer == "raw" else silver
        assert audit.passed and promotions == []
        intent, complete = P.read_stk_factor_pro_bootstrap_publication(
            **{key: args[key] for key in ("lake_root", "staging_root", "approval")},
            trade_date=args["source_complete"].trade_date,
            layer=layer,
        )
        assert intent.mode == "reuse"
        assert intent.expected_file_sha256 == intent.prior_file_sha256
        assert intent.expected_file_sha256 == complete.actual_file_sha256
        assert intent.expected_file_sha256 == factor_file_sha(target)
        assert intent.candidate.file_sha256 == factor_file_sha(candidate)
        assert intent.expected_file_sha256 != intent.candidate.file_sha256


@pytest.mark.parametrize("layer", ["raw", "silver"])
@pytest.mark.parametrize("changed_file", ["candidate", "target"])
def test_reuse_refuses_changed_candidate_or_original_target(
    tmp_path, monkeypatch, layer, changed_file
):
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path)
        candidate, target = _equivalent_target_on_build(conn, args, layer, monkeypatch)
        _, intent_path, _ = _paths(args, layer)
        promotions = _spy_promotions(monkeypatch, target)
        changed_sha = None

        def before_publish():
            nonlocal changed_sha
            if intent_path.exists() and changed_sha is None:
                _rewrite(conn, candidate if changed_file == "candidate" else target)
                changed_sha = factor_file_sha(target)

        args["before_publish"] = before_publish
        with pytest.raises(ValueError, match="候选|目标"):
            P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
            )
        assert changed_sha is not None and promotions == []
        assert factor_file_sha(target) == changed_sha
        assert conn.execute(
            "SELECT close FROM read_parquet(?,hive_partitioning=false)", [str(target)]
        ).fetchone() == ((10.0,) if changed_file == "candidate" else (99.0,))


@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_wrong_audit_identity_is_not_publication_authority(
    tmp_path, monkeypatch, layer
):
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path)
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
            )
        assert not target.exists()


@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_recovery_accepts_expected_target_with_candidate_already_moved(
    tmp_path, monkeypatch, layer
):
    with connection(tmp_path) as conn:
        args = _setup(conn, tmp_path)
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
            )
        assert target.is_file() and not candidate.exists()
        target_sha = factor_file_sha(target)
        intent_bytes = intent_path.read_bytes()
        promotions = _spy_promotions(monkeypatch, target)
        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", original
        )
        assert all(
            audit.passed
            for audit in P.publish_bootstrap_date(
                conn,
                **args,
                check_space=check_test_space,
            )
        )
        assert factor_file_sha(target) == target_sha
        assert intent_path.read_bytes() == intent_bytes
        assert promotions == [] and not candidate.exists()
