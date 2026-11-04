"""Per-file original Prod import and same-operation recovery; no event IO."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    approval_sha,
    atomic_promote,
    operation_path,
    operation_root,
    read_json,
    write_json,
)
from orchestrator.defs.checks.stk_factor_pro import (
    audit_stk_factor_pro_file,
    factor_content_sha,
    factor_file_identity,
    factor_file_sha,
)
from orchestrator.defs.io.stk_factor_pro_candidates import (
    BOOTSTRAP_DAY_SOURCE,
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


def _current_file_sha(path, *, known_records):
    identity = factor_file_identity(path) if path.exists() else None
    if path in known_records:
        _, digest, previous_identity = known_records[path]
        if identity != previous_identity:
            raise ValueError("bootstrap已核文件身份改变，停止本次处理")
        return digest
    digest = None if identity is None else factor_file_sha(path)
    if identity is not None and factor_file_identity(path) != identity:
        raise ValueError("bootstrap文件首次读取期间改变")
    known_records[path] = (None, digest, identity)
    return digest


def _register_audit(audit, *, known_records):
    previous = known_records.get(audit.path)
    identity = (
        previous[2]
        if previous is not None and previous[1] == audit.file_sha256
        else factor_file_identity(audit.path)
    )
    known_records[audit.path] = (
        audit,
        audit.file_sha256,
        identity,
    )
    return audit


def _intent_identity(
    *,
    lake_root,
    staging_root,
    approval,
    trade_date,
    layer,
    intent,
    known_records,
):
    digest = approval_sha(staging_root, approval, known_records=known_records)
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
            raw_path = operation_path(
                staging_root, approval, f"publication/{trade_date}/raw/complete.json"
            )
            if raw_path in known_records:
                raw_complete = known_records[raw_path][0]
            else:
                _, raw_complete = read_stk_factor_pro_bootstrap_publication(
                    lake_root=lake_root,
                    staging_root=staging_root,
                    approval=approval,
                    trade_date=trade_date,
                    layer="raw",
                    known_records=known_records,
                )
            if (
                raw_complete is None
                or raw_complete.source_complete_digest != intent.source_complete_digest
                or intent.raw_file_sha256 != raw_complete.actual_file_sha256
            ):
                raise ValueError("bootstrap Silver意图不对应原Raw完成事实")


def _complete_identity(
    *,
    lake_root,
    staging_root,
    approval,
    trade_date,
    layer,
    intent,
    complete,
    known_records,
):
    digest = approval_sha(staging_root, approval, known_records=known_records)
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
            != known_records[operation_path(staging_root, approval, intent_relative)][1]
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
    *, lake_root, staging_root, approval, trade_date, layer, known_records
):
    prefix = f"publication/{trade_date.isoformat()}/{layer}"
    intent_path = operation_path(staging_root, approval, f"{prefix}/intent.json")
    complete_path = operation_path(staging_root, approval, f"{prefix}/complete.json")
    first_intent = intent_path not in known_records
    first_complete = complete_path not in known_records
    intent = (
        read_json(
            intent_path,
            C.StkFactorProBootstrapPublicationIntent,
            known_records=known_records,
        )
        if first_intent
        else known_records[intent_path][0]
    )
    complete = (
        read_json(
            complete_path,
            C.StkFactorProBootstrapPublicationComplete,
            known_records=known_records,
        )
        if first_complete
        else known_records[complete_path][0]
    )
    try:
        if first_intent and intent is not None:
            _intent_identity(
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                trade_date=trade_date,
                layer=layer,
                intent=intent,
                known_records=known_records,
            )
        if first_complete and complete is not None:
            _complete_identity(
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                trade_date=trade_date,
                layer=layer,
                intent=intent,
                complete=complete,
                known_records=known_records,
            )
    except (TypeError, ValueError):
        # Parsed records are not confirmed facts when their first binding fails.
        if first_intent:
            known_records.pop(intent_path, None)
        if first_complete:
            known_records.pop(complete_path, None)
        raise
    return intent, complete


def write_stk_factor_pro_bootstrap_publication_intent(
    *, lake_root, staging_root, approval, record, check_space, known_records
):
    _intent_identity(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        trade_date=record.trade_date,
        layer=record.layer,
        intent=record,
        known_records=known_records,
    )
    return _write_verified_stk_factor_pro_bootstrap_publication_intent(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        record=record,
        check_space=check_space,
        known_records=known_records,
    )


def _write_verified_stk_factor_pro_bootstrap_publication_intent(
    *, lake_root, staging_root, approval, record, check_space, known_records
):
    candidate = operation_path(staging_root, approval, record.candidate.relative_path)
    if (
        _current_file_sha(candidate, known_records=known_records)
        != record.candidate.file_sha256
    ):
        raise ValueError("bootstrap发布候选文件摘要不符")
    target = _target(lake_root, record.trade_date, record.layer)
    current = _current_file_sha(target, known_records=known_records)
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
        known_records=known_records,
    )[0]


def write_stk_factor_pro_bootstrap_publication_complete(
    *,
    lake_root,
    staging_root,
    approval,
    record,
    check_space,
    known_records,
    date_results,
):
    diagnostics = record.audit.diagnostics_path
    if diagnostics is not None and diagnostics.is_absolute():
        root = operation_root(staging_root, approval)
        if not diagnostics.is_relative_to(root):
            raise ValueError("bootstrap诊断路径不属于operation")
        relative = diagnostics.relative_to(root)
        operation_path(staging_root, approval, relative.as_posix())
        record = replace(record, audit=replace(record.audit, diagnostics_path=relative))
    intent_path = operation_path(
        staging_root,
        approval,
        f"publication/{record.trade_date}/{record.layer}/intent.json",
    )
    if intent_path not in known_records:
        raise ValueError("bootstrap完成记录缺少本任务首次已核的意图")
    intent = known_records[intent_path][0]
    _complete_identity(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        trade_date=record.trade_date,
        layer=record.layer,
        intent=intent,
        complete=record,
        known_records=known_records,
    )
    if (
        _current_file_sha(
            _target(lake_root, record.trade_date, record.layer),
            known_records=known_records,
        )
        != record.actual_file_sha256
    ):
        raise ValueError("bootstrap完成记录目标身份不符")
    _register_audit(record.audit, known_records=known_records)
    check_space(
        "发布完成记录保存前",
        path=operation_root(staging_root, approval),
        trade_date=record.trade_date,
    )
    path = operation_path(
        staging_root,
        approval,
        f"publication/{record.trade_date.isoformat()}/{record.layer}/complete.json",
    )

    def saved_space(stage, **facts):
        if facts.get("event") == "record_saved":
            saved = known_records[path][0]
            entry = date_results[record.trade_date]
            entry[f"{record.layer}_complete"] = saved
            entry[f"{record.layer}_audit"] = known_records[saved.audit.path][0]
            entry["import_complete"] = all(
                entry[f"{layer}_complete"] is not None for layer in ("raw", "silver")
            )
            if entry["import_complete"]:
                entry["current_files_verified"] = True
                entry["needs_restore"] = False
        return check_space(stage, **facts)

    return write_json(
        path,
        record,
        check_space=saved_space,
        known_records=known_records,
    )[0]


def _verify_target_identity(
    *, lake_root, staging_root, approval, source, layer, complete, intent, known_records
):
    target = _target(lake_root, source.trade_date, layer)
    if (
        complete.source_complete_digest != source.source_complete_digest
        or not target.is_file()
        or _current_file_sha(target, known_records=known_records)
        != complete.actual_file_sha256
    ):
        raise ValueError("bootstrap已完成正式文件不存在或被改变，禁止旧源覆盖")
    if layer == "silver":
        raw = _target(lake_root, source.trade_date, "raw")
        if intent.raw_file_sha256 != _current_file_sha(
            raw, known_records=known_records
        ):
            raise ValueError("bootstrap Silver未对应当前Raw")
    return _register_audit(complete.audit, known_records=known_records)


def _candidate_fragment(connection, *, audit, root, relation, source, code_bounds):
    low, high = code_bounds
    content = (
        source.date_content_sha256
        if audit.layer == "raw"
        else factor_content_sha(connection, relation)
    )
    return C.StkFactorProFragment(
        audit.path.relative_to(root).as_posix(),
        audit.file_sha256,
        content,
        C.stk_factor_pro_schema_digest(audit.layer),
        audit.row_count,
        audit.observed_schema,
        audit.trade_date if audit.row_count else None,
        audit.trade_date if audit.row_count else None,
        low,
        high,
    )


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
    known_records,
    date_results,
):
    root = operation_root(staging_root, approval)
    day = source.trade_date
    entry = date_results[day]
    target = _target(lake_root, day, layer)
    candidate = operation_path(
        staging_root, approval, f"candidates/{day.isoformat()}/{layer}/part-000.parquet"
    )
    intent, complete = read_stk_factor_pro_bootstrap_publication(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        trade_date=day,
        layer=layer,
        known_records=known_records,
    )
    if complete is not None:
        audit = _verify_target_identity(
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            source=source,
            layer=layer,
            complete=complete,
            intent=intent,
            known_records=known_records,
        )
        entry[f"{layer}_audit"] = audit
        entry[f"{layer}_complete"] = complete
        return audit
    if (
        intent is not None
        and intent.source_complete_digest != source.source_complete_digest
    ):
        raise ValueError("bootstrap发布意图来源不符")

    def existing_audit(path):
        audit = audit_stk_factor_pro_file(
            connection,
            path=path,
            expected_relation=expected_relation,
            target_trade_date=day,
            layer=layer,
            known_records=known_records,
        )
        if not audit.passed:
            raise ValueError("bootstrap已有目标内容不同，停止并交管理员处理")
        return audit

    if intent is None:
        if candidate.exists():
            candidate_audit = existing_audit(candidate)
        else:
            check_space(
                "两层候选构造前",
                path=candidate,
                trade_date=day,
                layer=layer,
                rows=source.actual_rows,
            )
            if layer == "raw":
                candidate_audit = build_stk_factor_pro_raw_candidate_from_relation(
                    connection,
                    source_relation=BOOTSTRAP_DAY_SOURCE,
                    source_row_count=source.actual_rows,
                    target_trade_date=day,
                    prior_path=None,
                    candidate_path=candidate,
                    run_root=root,
                    known_records=known_records,
                )
            else:
                candidate_audit = build_stk_factor_pro_silver_candidate(
                    connection,
                    verified_raw_relation=RAW_EXPECTED,
                    raw_audit=entry["raw_audit"],
                    target_trade_date=day,
                    candidate_path=candidate,
                    run_root=root,
                    known_records=known_records,
                )
        if (
            not candidate_audit.passed
            or candidate_audit.path != candidate
            or candidate_audit.layer != layer
            or candidate_audit.trade_date != day
            or known_records[candidate][0] != candidate_audit
        ):
            raise ValueError("bootstrap候选未通过完整业务对账")
        if layer == "raw":
            code_bounds = connection.execute(
                f"SELECT min(ts_code),max(ts_code) FROM {expected_relation}"
            ).fetchone()
        else:
            raw_intent = known_records[
                operation_path(
                    staging_root, approval, f"publication/{day}/raw/intent.json"
                )
            ][0]
            code_bounds = (
                raw_intent.candidate.first_code,
                raw_intent.candidate.last_code,
            )
        fragment = _candidate_fragment(
            connection,
            audit=candidate_audit,
            root=root,
            relation=expected_relation,
            source=source,
            code_bounds=code_bounds,
        )
        check_space(
            "候选完整检查通过",
            path=candidate,
            trade_date=day,
            layer=layer,
            rows=candidate_audit.row_count,
            event="candidate_verified",
        )
        actual = existing_audit(target) if target.exists() else None
        prior = None if actual is None else actual.file_sha256
        if actual is None:
            known_records[target] = (None, None, None)
        before_publish()
        if (
            _current_file_sha(candidate, known_records=known_records)
            != candidate_audit.file_sha256
        ):
            raise ValueError("bootstrap保存意图前候选已改变")
        if _current_file_sha(target, known_records=known_records) != prior:
            raise ValueError("bootstrap保存意图前目标已改变")
        intent = C.StkFactorProBootstrapPublicationIntent(
            1,
            approval.operation_id,
            approval_sha(staging_root, approval, known_records=known_records),
            day,
            layer,
            source.source_complete_digest,
            entry["raw_audit"].file_sha256 if layer == "silver" else None,
            "reuse" if actual is not None else "replace",
            prior,
            fragment,
            prior or candidate_audit.file_sha256,
            "0" * 64,
            datetime.now(ZoneInfo(C.STK_FACTOR_PRO_TIMEZONE)),
        )
        intent = replace(
            intent, intent_digest=C.stk_factor_pro_bootstrap_intent_digest(intent)
        )
        _write_verified_stk_factor_pro_bootstrap_publication_intent(
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            record=intent,
            check_space=check_space,
            known_records=known_records,
        )
    else:
        # A new execution confirms only the actual artifact needed for recovery.
        actual = existing_audit(target) if target.exists() else None
        if actual is not None and actual.file_sha256 != intent.expected_file_sha256:
            raise ValueError("bootstrap恢复目标既非原目标亦非本次结果")
        candidate_audit = None
        if actual is None:
            if not candidate.is_file():
                raise ValueError("bootstrap恢复缺本次候选")
            candidate_audit = existing_audit(candidate)
            if candidate_audit.file_sha256 != intent.candidate.file_sha256:
                raise ValueError("bootstrap恢复候选与原意图不符")
            known_records[target] = (None, None, None)

    check_space(
        "正式提升前",
        path=target if actual is not None else candidate,
        trade_date=day,
        layer=layer,
        rows=source.actual_rows,
    )
    before_publish()
    if layer == "silver" and (
        _current_file_sha(_target(lake_root, day, "raw"), known_records=known_records)
        != intent.raw_file_sha256
    ):
        raise ValueError("bootstrap Silver提升前Raw身份已改变")
    if actual is None:
        if (
            _current_file_sha(target, known_records=known_records)
            != intent.prior_file_sha256
        ):
            raise ValueError("bootstrap恢复目标既非原目标亦非本次结果")
        if (
            _current_file_sha(candidate, known_records=known_records)
            != intent.candidate.file_sha256
        ):
            raise ValueError("bootstrap提升前候选已改变")
        audit = replace(candidate_audit, path=target)

        def replaced():
            entry["replaced_layers"].add(layer)
            entry[f"{layer}_audit"] = audit
            entry["current_files_verified"] = False
            known_records[candidate] = (None, None, None)
            _register_audit(audit, known_records=known_records)

        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_promote(candidate, target, on_replaced=replaced)
    else:
        if (
            _current_file_sha(target, known_records=known_records)
            != intent.expected_file_sha256
        ):
            raise ValueError("bootstrap已核目标在发布前改变")
        audit = actual
        entry[f"{layer}_audit"] = audit
    intent_relative = f"publication/{day.isoformat()}/{layer}/intent.json"
    complete = C.StkFactorProBootstrapPublicationComplete(
        1,
        approval.operation_id,
        approval_sha(staging_root, approval, known_records=known_records),
        day,
        layer,
        source.source_complete_digest,
        intent_relative,
        known_records[operation_path(staging_root, approval, intent_relative)][1],
        intent.intent_digest,
        audit.file_sha256,
        audit.row_count,
        intent.candidate.schema_content_digest,
        intent.candidate.content_sha256,
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
        known_records=known_records,
        date_results=date_results,
    )
    return audit


def publish_bootstrap_date(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    source_complete,
    source_record_sha256,
    source_relation,
    before_publish,
    check_space,
    known_records,
    date_results,
):
    """Return two verified formal audits; caller handles coverage afterward."""
    _roots(lake_root, staging_root)
    day = source_complete.trade_date
    entry = date_results[day]
    source_fact = known_records[
        operation_path(
            staging_root, approval, f"source/dates/{day}/source-complete.json"
        )
    ]
    if (
        source_fact[0] != source_complete
        or source_fact[1] != source_record_sha256
        or source_relation != BOOTSTRAP_DAY_SOURCE
    ):
        raise ValueError("bootstrap发布缺本operation首次已核的完整日源交接")
    entry["source_complete"] = source_complete
    entry["source_record_sha256"] = source_record_sha256
    targets = tuple(_target(lake_root, day, layer) for layer in ("raw", "silver"))
    if source_complete.source_empty:
        if any(path.exists() for path in targets):
            raise ValueError("bootstrap原空源与已有正式目标冲突")
        for path in targets:
            known_records[path] = (None, None, None)
        entry["import_complete"] = True
        entry["current_files_verified"] = True
        entry["needs_restore"] = False
        return None, None
    raw_intent, raw_complete = read_stk_factor_pro_bootstrap_publication(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        trade_date=day,
        layer="raw",
        known_records=known_records,
    )
    if raw_complete is None:
        candidate = operation_path(
            staging_root,
            approval,
            f"candidates/{day.isoformat()}/raw/part-000.parquet",
        )
        if raw_intent is not None or candidate.exists():
            connection.execute(
                f"CREATE TEMP TABLE {RAW_EXPECTED} AS SELECT * FROM {source_relation}"
            )
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
            known_records=known_records,
            date_results=date_results,
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
            known_records=known_records,
        )
    entry["raw_audit"] = raw
    entry["raw_complete"] = known_records[
        operation_path(staging_root, approval, f"publication/{day}/raw/complete.json")
    ][0]
    silver_intent, silver_complete = read_stk_factor_pro_bootstrap_publication(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        trade_date=day,
        layer="silver",
        known_records=known_records,
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
            known_records=known_records,
        )
    else:
        if raw_complete is not None:
            connection.execute(
                f"CREATE TEMP TABLE {RAW_EXPECTED} AS SELECT * FROM {source_relation}"
            )
        projection = ",".join(
            "CAST(strptime(trade_date,'%Y%m%d') AS DATE) AS trade_date"
            if name == "trade_date"
            else f'"{name}"'
            for name in C.STK_FACTOR_PRO_SOURCE_COLUMNS
        )
        candidate = operation_path(
            staging_root,
            approval,
            f"candidates/{day.isoformat()}/silver/part-000.parquet",
        )
        if silver_intent is not None or candidate.exists():
            connection.execute(
                f"CREATE TEMP TABLE {SILVER_EXPECTED} AS SELECT {projection} FROM {RAW_EXPECTED}"
            )
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
            known_records=known_records,
            date_results=date_results,
        )
    entry["silver_audit"] = silver
    entry["silver_complete"] = known_records[
        operation_path(
            staging_root, approval, f"publication/{day}/silver/complete.json"
        )
    ][0]
    entry["import_complete"] = True
    entry["current_files_verified"] = True
    entry["needs_restore"] = False
    for audit in (raw, silver):
        check_space(
            "正式两层发布完成",
            path=audit.path,
            trade_date=day,
            layer=audit.layer,
            rows=audit.row_count,
            event="publication_verified",
        )
    return raw, silver
