"""Per-file original Prod import and same-operation recovery; no event IO."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    approval_sha,
    atomic_promote,
    fragment_from_relation,
    load_complete_source,
    operation_path,
    operation_root,
    read_json,
    read_stk_factor_pro_bootstrap_source_complete,
    resource_cleanup,
    write_json,
)
from orchestrator.defs.checks.stk_factor_pro import (
    audit_stk_factor_pro_file,
    factor_content_sha,
    factor_file_sha,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.stk_factor_pro_candidates import (
    BOOTSTRAP_DAY_SOURCE,
    DAY_PRIOR,
    RAW_EXPECTED,
    SILVER_EXPECTED,
    build_stk_factor_pro_raw_candidate_from_relation,
    build_stk_factor_pro_silver_candidate,
)
from orchestrator.defs.io.stk_factor_pro_publication import _roots
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C


def _target(lake_root, trade_date, layer):
    if layer not in ("raw", "silver"):
        raise ValueError("bootstrap发布层不合法")
    return (
        raw_stk_factor_pro_path if layer == "raw" else silver_stock_factor_pro_path
    )(lake_root, trade_date.isoformat())


def _publication_identity(
    *, lake_root, staging_root, approval, trade_date, layer, intent, complete
):
    digest = approval_sha(staging_root, approval)
    candidate_relative = f"candidates/{trade_date.isoformat()}/{layer}/part-000.parquet"
    if intent is not None:
        if (
            intent.operation_id,
            intent.approval_digest,
            intent.trade_date,
            intent.layer,
        ) != (approval.operation_id, digest, trade_date, layer):
            raise ValueError("bootstrap发布意图身份不符")
        if (
            intent.candidate.relative_path != candidate_relative
            or intent.intent_digest != C.stk_factor_pro_bootstrap_intent_digest(intent)
        ):
            raise ValueError("bootstrap发布候选位置或意图摘要错误")
        operation_path(staging_root, approval, candidate_relative)
        if intent.mode == "replace" and intent.prior_file_sha256 is not None:
            raise ValueError("bootstrap首次替换只允许空目标")
        if intent.mode == "reuse" and (
            intent.prior_file_sha256 is None
            or intent.expected_file_sha256 != intent.prior_file_sha256
        ):
            raise ValueError("bootstrap等价复用目标摘要错误")
        if layer == "silver":
            _, raw_complete = read_stk_factor_pro_bootstrap_publication(
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                trade_date=trade_date,
                layer="raw",
            )
            if (
                raw_complete is None
                or raw_complete.source_complete_digest != intent.source_complete_digest
                or intent.raw_file_sha256 != raw_complete.actual_file_sha256
            ):
                raise ValueError("bootstrap Silver意图不对应原Raw完成事实")
            if (
                complete is None
                and factor_file_sha(_target(lake_root, trade_date, "raw"))
                != intent.raw_file_sha256
            ):
                raise ValueError("bootstrap Silver提升前Raw身份已改变")
    if complete is not None:
        if intent is None:
            raise ValueError("bootstrap完成记录缺原意图")
        intent_relative = f"publication/{trade_date.isoformat()}/{layer}/intent.json"
        if (
            (
                complete.operation_id,
                complete.approval_digest,
                complete.trade_date,
                complete.layer,
            )
            != (approval.operation_id, digest, trade_date, layer)
            or complete.intent_relative_path != intent_relative
            or complete.intent_file_sha256
            != factor_file_sha(operation_path(staging_root, approval, intent_relative))
            or complete.intent_digest != intent.intent_digest
            or complete.source_complete_digest != intent.source_complete_digest
            or complete.actual_file_sha256 != intent.expected_file_sha256
            or complete.audit.path != _target(lake_root, trade_date, layer)
            or complete.audit.trade_date != trade_date
            or complete.audit.layer != layer
            or complete.audit.file_sha256 != complete.actual_file_sha256
            or complete.actual_rows != complete.audit.row_count
            or not complete.audit.passed
            or complete.schema_content_digest != C.stk_factor_pro_schema_digest(layer)
            or complete.schema_content_digest != intent.candidate.schema_content_digest
            or complete.content_sha256 != intent.candidate.content_sha256
            or complete.actual_rows != intent.candidate.row_count
            or tuple(name for name, _ in complete.audit.comparison.changed_field_counts)
            != C.STK_FACTOR_PRO_SOURCE_COLUMNS[2:]
        ):
            raise ValueError("bootstrap发布完成记录与意图/正式audit不符")
        diagnostics = complete.audit.diagnostics_path
        if diagnostics is not None:
            if diagnostics.is_absolute():
                raise ValueError("bootstrap持久化诊断路径必须是operation内相对路径")
            operation_path(staging_root, approval, diagnostics.as_posix())


def read_stk_factor_pro_bootstrap_publication(
    *, lake_root, staging_root, approval, trade_date, layer
):
    prefix = f"publication/{trade_date.isoformat()}/{layer}"
    intent = read_json(
        operation_path(staging_root, approval, f"{prefix}/intent.json"),
        C.StkFactorProBootstrapPublicationIntent,
    )
    complete = read_json(
        operation_path(staging_root, approval, f"{prefix}/complete.json"),
        C.StkFactorProBootstrapPublicationComplete,
    )
    _publication_identity(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        trade_date=trade_date,
        layer=layer,
        intent=intent,
        complete=complete,
    )
    return intent, complete


def write_stk_factor_pro_bootstrap_publication_intent(
    *, lake_root, staging_root, approval, record, check_space
):
    _publication_identity(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        trade_date=record.trade_date,
        layer=record.layer,
        intent=record,
        complete=None,
    )
    candidate = operation_path(staging_root, approval, record.candidate.relative_path)
    if factor_file_sha(candidate) != record.candidate.file_sha256:
        raise ValueError("bootstrap发布候选文件摘要不符")
    target = _target(lake_root, record.trade_date, record.layer)
    current = factor_file_sha(target) if target.exists() else None
    if current != record.prior_file_sha256:
        raise ValueError("bootstrap保存意图前目标已改变")
    relative = f"publication/{record.trade_date.isoformat()}/{record.layer}/intent.json"
    check_space(
        "发布意图保存前",
        path=operation_path(staging_root, approval, relative),
        trade_date=record.trade_date,
    )
    return write_json(
        operation_path(staging_root, approval, relative),
        record,
        check_space=check_space,
    )


def write_stk_factor_pro_bootstrap_publication_complete(
    *, lake_root, staging_root, approval, record, check_space
):
    diagnostics = record.audit.diagnostics_path
    if diagnostics is not None and diagnostics.is_absolute():
        root = operation_root(staging_root, approval)
        if not diagnostics.is_relative_to(root):
            raise ValueError("bootstrap诊断路径不属于operation")
        relative = diagnostics.relative_to(root)
        operation_path(staging_root, approval, relative.as_posix())
        record = replace(record, audit=replace(record.audit, diagnostics_path=relative))
    intent, _ = read_stk_factor_pro_bootstrap_publication(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        trade_date=record.trade_date,
        layer=record.layer,
    )
    _publication_identity(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        trade_date=record.trade_date,
        layer=record.layer,
        intent=intent,
        complete=record,
    )
    if (
        factor_file_sha(_target(lake_root, record.trade_date, record.layer))
        != record.actual_file_sha256
    ):
        raise ValueError("bootstrap完成记录目标身份不符")
    check_space(
        "发布完成记录保存前",
        path=operation_root(staging_root, approval),
        trade_date=record.trade_date,
    )
    return write_json(
        operation_path(
            staging_root,
            approval,
            f"publication/{record.trade_date.isoformat()}/{record.layer}/complete.json",
        ),
        record,
        check_space=check_space,
    )


def _verify_target_identity(
    *, lake_root, staging_root, approval, source, layer, complete, intent
):
    target = _target(lake_root, source.trade_date, layer)
    if (
        complete.source_complete_digest != source.source_complete_digest
        or not target.is_file()
        or factor_file_sha(target) != complete.actual_file_sha256
    ):
        raise ValueError("bootstrap已完成正式文件不存在或被改变，禁止旧源覆盖")
    if layer == "silver":
        raw = _target(lake_root, source.trade_date, "raw")
        if intent.raw_file_sha256 != factor_file_sha(raw):
            raise ValueError("bootstrap Silver未对应当前Raw")
    return complete.audit


def _publish_layer(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    source,
    layer,
    expected_relation,
    before_publish,
    check_space,
):
    root = operation_root(staging_root, approval)
    target = _target(lake_root, source.trade_date, layer)
    relative = f"candidates/{source.trade_date.isoformat()}/{layer}/part-000.parquet"
    candidate = operation_path(staging_root, approval, relative)
    intent, complete = read_stk_factor_pro_bootstrap_publication(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        trade_date=source.trade_date,
        layer=layer,
    )
    if complete is not None:
        return _verify_target_identity(
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            source=source,
            layer=layer,
            complete=complete,
            intent=intent,
        )
    if (
        intent is not None
        and intent.source_complete_digest != source.source_complete_digest
    ):
        raise ValueError("bootstrap发布意图来源不符")
    creating_intent = intent is None
    if intent is None:
        if not candidate.exists():
            check_space(
                "两层候选构造前",
                path=candidate,
                trade_date=source.trade_date,
                layer=layer,
                rows=source.actual_rows,
            )
            if layer == "raw":
                candidate_audit = build_stk_factor_pro_raw_candidate_from_relation(
                    connection,
                    source_relation=BOOTSTRAP_DAY_SOURCE,
                    target_trade_date=source.trade_date,
                    prior_path=None,
                    candidate_path=candidate,
                    run_root=root,
                )
            else:
                candidate_audit = build_stk_factor_pro_silver_candidate(
                    connection,
                    verified_raw_path=_target(lake_root, source.trade_date, "raw"),
                    target_trade_date=source.trade_date,
                    candidate_path=candidate,
                    run_root=root,
                )
        else:
            candidate_audit = audit_stk_factor_pro_file(
                connection,
                path=candidate,
                expected_relation=expected_relation,
                target_trade_date=source.trade_date,
                layer=layer,
            )
        if (
            not candidate_audit.passed
            or candidate_audit.path != candidate
            or candidate_audit.layer != layer
            or candidate_audit.trade_date != source.trade_date
        ):
            raise ValueError("bootstrap候选未通过完整业务对账")
        validated_candidate_sha = candidate_audit.file_sha256
        fragment = (
            fragment_from_relation(
                connection,
                path=candidate,
                operation_root=root,
                relation=expected_relation,
            )
            if layer == "raw"
            else _silver_fragment(
                connection, candidate, root, expected_relation, source.trade_date
            )
        )
        if (
            fragment.file_sha256 != validated_candidate_sha
            or fragment.row_count != candidate_audit.row_count
            or fragment.observed_schema != candidate_audit.observed_schema
            or fragment.schema_content_digest != C.stk_factor_pro_schema_digest(layer)
        ):
            raise ValueError("bootstrap候选描述与原完整检查不符")
        check_space(
            "候选完整检查通过",
            path=candidate,
            trade_date=source.trade_date,
            layer=layer,
            rows=candidate_audit.row_count,
            event="candidate_verified",
        )
        current = factor_file_sha(target) if target.exists() else None
        if current is not None:
            old = audit_stk_factor_pro_file(
                connection,
                path=target,
                expected_relation=expected_relation,
                target_trade_date=source.trade_date,
                layer=layer,
            )
            if not old.passed or old.file_sha256 != current:
                raise ValueError("bootstrap已有目标内容不同，停止并交管理员处理")
            current = old.file_sha256
        before_publish()
        if factor_file_sha(candidate) != validated_candidate_sha:
            raise ValueError("bootstrap保存意图前候选已改变")
        if (factor_file_sha(target) if target.exists() else None) != current:
            raise ValueError("bootstrap保存意图前目标已改变")
        intent = C.StkFactorProBootstrapPublicationIntent(
            1,
            approval.operation_id,
            approval_sha(staging_root, approval),
            source.trade_date,
            layer,
            source.source_complete_digest,
            factor_file_sha(_target(lake_root, source.trade_date, "raw"))
            if layer == "silver"
            else None,
            "reuse" if current is not None else "replace",
            current,
            fragment,
            current or validated_candidate_sha,
            "0" * 64,
            datetime.now(ZoneInfo(C.STK_FACTOR_PRO_TIMEZONE)),
        )
        intent = replace(
            intent, intent_digest=C.stk_factor_pro_bootstrap_intent_digest(intent)
        )
        write_stk_factor_pro_bootstrap_publication_intent(
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            record=intent,
            check_space=check_space,
        )
    check_space(
        "正式提升前",
        path=candidate if candidate.exists() else target,
        trade_date=source.trade_date,
        layer=layer,
        rows=source.actual_rows,
    )
    before_publish()
    if (
        layer == "silver"
        and factor_file_sha(_target(lake_root, source.trade_date, "raw"))
        != intent.raw_file_sha256
    ):
        raise ValueError("bootstrap Silver提升前Raw身份已改变")
    current = factor_file_sha(target) if target.exists() else None
    # A completed replace may have moved the candidate before the checkpoint
    # was written. New intents and still-present recovery candidates must
    # nevertheless remain the exact file accepted by the original audit.
    if (creating_intent or candidate.exists()) and (
        not candidate.is_file()
        or factor_file_sha(candidate) != intent.candidate.file_sha256
    ):
        raise ValueError("bootstrap提升前候选已改变")
    if current != intent.expected_file_sha256:
        if (
            current != intent.prior_file_sha256
            or not candidate.is_file()
            or factor_file_sha(candidate) != intent.candidate.file_sha256
        ):
            raise ValueError("bootstrap恢复目标既非原目标亦非本次结果")
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_promote(candidate, target)
    audit = audit_stk_factor_pro_file(
        connection,
        path=target,
        expected_relation=expected_relation,
        target_trade_date=source.trade_date,
        layer=layer,
    )
    if not audit.passed or audit.file_sha256 != intent.expected_file_sha256:
        raise ValueError("bootstrap正式发布读回不符")
    complete = C.StkFactorProBootstrapPublicationComplete(
        1,
        approval.operation_id,
        approval_sha(staging_root, approval),
        source.trade_date,
        layer,
        source.source_complete_digest,
        f"publication/{source.trade_date.isoformat()}/{layer}/intent.json",
        factor_file_sha(
            operation_path(
                staging_root,
                approval,
                f"publication/{source.trade_date.isoformat()}/{layer}/intent.json",
            )
        ),
        intent.intent_digest,
        audit.file_sha256,
        audit.row_count,
        C.stk_factor_pro_schema_digest(layer),
        factor_content_sha(connection, expected_relation),
        1,
        audit,
        datetime.now(ZoneInfo(C.STK_FACTOR_PRO_TIMEZONE)),
    )
    write_stk_factor_pro_bootstrap_publication_complete(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        record=complete,
        check_space=check_space,
    )
    return audit


def _silver_fragment(connection, path, root, relation, trade_date):
    rows = connection.execute(
        f"SELECT count(*),min(ts_code),max(ts_code) FROM {relation}"
    ).fetchone()
    return C.StkFactorProFragment(
        path.relative_to(root).as_posix(),
        factor_file_sha(path),
        factor_content_sha(connection, relation),
        C.stk_factor_pro_schema_digest("silver"),
        rows[0],
        tuple(C.STK_FACTOR_PRO_SILVER_COLUMN_TYPES.items()),
        trade_date if rows[0] else None,
        trade_date if rows[0] else None,
        rows[1],
        rows[2],
    )


def publish_bootstrap_date(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    source_complete,
    before_publish,
    check_space,
    verification=None,
):
    """Return two verified formal audits; caller handles coverage afterward."""
    _roots(lake_root, staging_root)
    day = source_complete.trade_date
    saved_source = read_stk_factor_pro_bootstrap_source_complete(
        connection,
        staging_root=staging_root,
        approval=approval,
        trade_date=day,
    )
    if saved_source != source_complete:
        raise ValueError("bootstrap发布缺本operation已核完整日源")
    targets = tuple(_target(lake_root, day, layer) for layer in ("raw", "silver"))
    if source_complete.source_empty:
        if any(path.exists() for path in targets):
            raise ValueError("bootstrap原空源与已有正式目标冲突")
        return None, None
    raw_intent, raw_complete = read_stk_factor_pro_bootstrap_publication(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        trade_date=day,
        layer="raw",
    )
    tables = (SILVER_EXPECTED, RAW_EXPECTED, DAY_PRIOR, BOOTSTRAP_DAY_SOURCE)
    releases = tuple(
        lambda name=name: connection.execute(f"DROP TABLE IF EXISTS {name}")
        for name in tables
    )
    with resource_cleanup(*releases):
        if raw_complete is None:
            load_complete_source(
                connection,
                staging_root=staging_root,
                approval=approval,
                record=source_complete,
                verification=verification,
            )
            connection.execute(
                f"CREATE TEMP TABLE {RAW_EXPECTED} AS SELECT * FROM {BOOTSTRAP_DAY_SOURCE}"
            )
            # Fresh builder owns RAW_EXPECTED; drop it before its construction.
            candidate = operation_path(
                staging_root,
                approval,
                f"candidates/{day.isoformat()}/raw/part-000.parquet",
            )
            if raw_intent is None and not candidate.exists():
                connection.execute(f"DROP TABLE {RAW_EXPECTED}")
            raw = _publish_layer(
                connection,
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                source=source_complete,
                layer="raw",
                expected_relation=RAW_EXPECTED,
                before_publish=before_publish,
                check_space=check_space,
            )
        else:
            raw = _verify_target_identity(
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                source=source_complete,
                layer="raw",
                complete=raw_complete,
                intent=raw_intent,
            )
        silver_intent, silver_complete = read_stk_factor_pro_bootstrap_publication(
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            trade_date=day,
            layer="silver",
        )
        if silver_complete is not None:
            silver = _verify_target_identity(
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                source=source_complete,
                layer="silver",
                complete=silver_complete,
                intent=silver_intent,
            )
        else:
            projection = ",".join(
                "CAST(strptime(trade_date,'%Y%m%d') AS DATE) AS trade_date"
                if name == "trade_date"
                else f'"{name}"'
                for name in C.STK_FACTOR_PRO_SOURCE_COLUMNS
            )
            connection.execute(
                f"CREATE TEMP TABLE {SILVER_EXPECTED} AS SELECT {projection} FROM {read_parquet(raw.path, hive_partitioning=False)}"
            )
            candidate = operation_path(
                staging_root,
                approval,
                f"candidates/{day.isoformat()}/silver/part-000.parquet",
            )
            if silver_intent is None and not candidate.exists():
                connection.execute(f"DROP TABLE {SILVER_EXPECTED}")
            silver = _publish_layer(
                connection,
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                source=source_complete,
                layer="silver",
                expected_relation=SILVER_EXPECTED,
                before_publish=before_publish,
                check_space=check_space,
            )
        for audit in (raw, silver):
            check_space(
                "正式两层读回通过",
                path=audit.path,
                trade_date=day,
                layer=audit.layer,
                rows=audit.row_count,
                event="publication_verified",
            )
        return raw, silver
