"""Current-run per-file publication; no old candidate/checkpoint continuation."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, fields, replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.checks.stk_factor_pro import (
    audit_stk_factor_pro_file,
    factor_file_sha,
)
from orchestrator.defs.io.stk_factor_pro_candidates import (
    DAY_SOURCE,
    RAW_EXPECTED,
    SILVER_EXPECTED,
    build_stk_factor_pro_raw_candidate,
    build_stk_factor_pro_silver_candidate,
    require_stk_factor_pro_candidate_path,
)
from orchestrator.defs.io.stk_factor_pro_candidates import (
    require_stk_factor_pro_safe_path as _safe,
)
from orchestrator.defs.io.stk_factor_pro_download import (
    require_stk_factor_pro_current_day_source,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    stk_factor_pro_run_staging_root,
)
from orchestrator.defs.run_contracts.stk_factor_pro import (
    STK_FACTOR_PRO_TIMEZONE,
    ContractIdentity,
    PublishedTarget,
    RecordRef,
    RunIdentity,
    StkFactorProPublicationRecord,
)


def _roots(lake: Path, staging: Path) -> None:
    for root in (lake, staging):
        _safe(root)
        if not root.is_dir():
            raise ValueError("技术因子目标根目录不存在")
    if lake == staging or lake in staging.parents or staging in lake.parents:
        raise ValueError("技术因子正式根和staging不能重叠")
    if any(
        root == Path("/Volumes") or Path("/Volumes") in root.parents
        for root in (lake, staging)
    ) and (lake, staging) != (Path(DEFAULT_LAKE_ROOT), Path(DEFAULT_LAKE_STAGING_ROOT)):
        raise ValueError("技术因子仅允许既定正式Volumes根")
    if lake == Path(DEFAULT_LAKE_ROOT) and not lake.parent.is_mount():
        raise ValueError("技术因子正式数据卷未挂载，禁止写入")
    if lake.stat().st_dev != staging.stat().st_dev:
        raise ValueError("技术因子候选和正式目标必须同一文件系统")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def read_stk_factor_pro_publication_record(path: Path) -> StkFactorProPublicationRecord:
    _safe(path)
    value = json.loads(path.read_text())
    if type(value) is not dict or set(value) != {
        field.name for field in fields(StkFactorProPublicationRecord)
    }:
        raise ValueError("技术因子发布记录缺字段或含未知字段")
    original = value.copy()
    if type(value["identity"]) is not dict or type(value["contract"]) is not dict:
        raise ValueError("技术因子发布记录identity/contract必须是完整对象")
    identity = value["identity"].copy()
    for key in ("execution_day", "target_trade_date", "previous_trade_date"):
        identity[key] = date.fromisoformat(identity[key])
    value["identity"] = RunIdentity(**identity)
    value["contract"] = ContractIdentity(**value["contract"])
    value["trade_date"] = date.fromisoformat(value["trade_date"])
    if value["verified_at"] is not None:
        value["verified_at"] = datetime.fromisoformat(value["verified_at"])
    record = StkFactorProPublicationRecord(**value)
    if _json_value(asdict(record)) != original:
        raise ValueError("技术因子发布记录日期或时刻不是规范表示")
    expected_suffix = (
        f"run_id={record.identity.creator_run_id}",
        "publication",
        "day",
        record.trade_date.isoformat(),
        record.layer,
        f"{record.stage}.json",
    )
    if path.parts[-len(expected_suffix) :] != expected_suffix:
        raise ValueError("技术因子发布记录物理路径与run、日期、层或状态不符")
    return record


def _write_record(path: Path, record: StkFactorProPublicationRecord) -> None:
    _safe(path)
    if path.exists():
        raise ValueError("技术因子不沿已有发布记录续跑，请创建重新下载的新任务")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    _safe(temporary)
    payload = json.dumps(
        _json_value(asdict(record)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    with temporary.open("x") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)
    if read_stk_factor_pro_publication_record(path) != record:
        raise ValueError("技术因子发布记录读回不符")


def _hash_if_exists(path: Path) -> str | None:
    _safe(path)
    return factor_file_sha(path) if path.is_file() else None


def _publish_file(
    connection,
    *,
    source,
    run_root,
    target,
    candidate_audit,
    prior,
    expected_relation,
    check_cancel,
    raw_guard,
):
    candidate = candidate_audit.path
    for path in (candidate, target):
        _safe(path)
    if not candidate.is_relative_to(run_root) or not candidate_audit.passed:
        raise ValueError("技术因子候选未通过检查或不属于当前run")
    layer = candidate_audit.layer
    directory = (
        run_root
        / "publication"
        / "day"
        / source.identity.target_trade_date.isoformat()
        / layer
    )
    if (directory / "intent.json").exists() or (directory / "complete.json").exists():
        raise ValueError("技术因子不得使用已有intent或complete继续发布")
    if _hash_if_exists(target) != prior:
        raise ValueError("技术因子正式目标在构造候选时已改变")
    unchanged = False
    if prior is not None:
        # Candidate and current target must both equal this run's independent expected relation.
        current_audit = audit_stk_factor_pro_file(
            connection,
            path=target,
            expected_relation=expected_relation,
            target_trade_date=source.identity.target_trade_date,
            layer=layer,
        )
        unchanged = current_audit.passed
    raw_guard()
    with candidate.open("rb") as stream:
        os.fsync(stream.fileno())
    mode = "reuse" if unchanged else "replace"
    record = StkFactorProPublicationRecord(
        1,
        source.identity,
        "day",
        source.identity.target_trade_date,
        layer,
        source.contract,
        source.scope_digest,
        None,
        source.day_source_digest,
        None,
        str(target),
        candidate.relative_to(run_root).as_posix(),
        prior,
        candidate_audit.file_sha256,
        candidate_audit.row_count,
        prior if unchanged else candidate_audit.file_sha256,
        mode,
        "intent",
        None,
        None,
        None,
        None,
        None,
    )
    _write_record(directory / "intent.json", record)
    check_cancel()
    raw_guard()
    if (
        _hash_if_exists(target) != prior
        or factor_file_sha(candidate) != record.candidate_sha256
    ):
        raise ValueError("技术因子目标或候选在发布前改变")
    target.parent.mkdir(parents=True, exist_ok=True)
    _safe(target)
    if target.parent.stat().st_dev != candidate.stat().st_dev:
        raise ValueError("技术因子提升跨文件系统")
    if shutil.disk_usage(target.parent).free < candidate.stat().st_size:
        raise ValueError("技术因子发布磁盘空间不足")
    if not unchanged:
        os.replace(candidate, target)
        _fsync_directory(target.parent)
    # No cancellation boundary here: finish facts for a file already replaced.
    actual_sha = factor_file_sha(target)
    observed = tuple(
        (r[0], r[1])
        for r in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(target)],
        ).fetchall()
    )
    row_count = connection.execute(
        "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)", [str(target)]
    ).fetchone()[0]
    if (
        actual_sha != record.expected_published_sha256
        or observed != candidate_audit.observed_schema
        or row_count != candidate_audit.row_count
        or factor_file_sha(target) != actual_sha
    ):
        raise ValueError("技术因子正式文件与已完整校验的候选身份不符")
    # os.replace moved those exact validated bytes. Reuse the all-field audit;
    # do not scan/join 259 columns a second time just to emit the same check.
    actual = replace(candidate_audit, path=target, file_sha256=actual_sha)
    raw_guard()
    if not actual.passed or actual.file_sha256 != record.expected_published_sha256:
        raise ValueError("技术因子正式文件发布读回不符")
    complete = replace(
        record,
        stage="complete",
        verified_at=datetime.now(ZoneInfo(STK_FACTOR_PRO_TIMEZONE)),
        actual_sha256=actual.file_sha256,
        actual_rows=actual.row_count,
    )
    complete_path = directory / "complete.json"
    _write_record(complete_path, complete)
    reference = RecordRef(
        source.identity.creator_run_id,
        complete_path.relative_to(run_root).as_posix(),
        factor_file_sha(complete_path),
    )
    return PublishedTarget(
        source.identity.target_trade_date,
        layer,
        False,
        actual.file_sha256,
        actual.row_count,
        reference,
        0,
    ), actual


def publish_stk_factor_pro_day(
    connection, *, source, lake_root: Path, staging_root: Path, check_cancel
):
    require_stk_factor_pro_current_day_source(connection, source)
    _roots(lake_root, staging_root)
    day = source.identity.target_trade_date.isoformat()
    root = stk_factor_pro_run_staging_root(
        staging_root, source.identity.creator_run_id, day
    )
    raw = raw_stk_factor_pro_path(lake_root, day)
    silver = silver_stock_factor_pro_path(lake_root, day)
    for path in (root, raw, silver):
        _safe(path)
    raw_candidate = root / "candidates" / "day" / "raw" / "data.parquet"
    silver_candidate = root / "candidates" / "day" / "silver" / "data.parquet"
    for path in (raw_candidate, silver_candidate):
        require_stk_factor_pro_candidate_path(candidate_path=path, run_root=root)
    if (root / "candidates" / "day").exists() or (
        root / "publication" / "day"
    ).exists():
        raise ValueError("技术因子当前run已有日候选或发布记录，不接受续跑")
    source_rows = connection.execute(f"SELECT count(*) FROM {DAY_SOURCE}").fetchone()[0]
    if source_rows == 0 and not raw.exists():
        if silver.exists():
            raise ValueError("技术因子仅存在Silver，缺少对应Raw，请管理员处理")
        return
    check_cancel()
    prior_raw = _hash_if_exists(raw)
    raw_audit = build_stk_factor_pro_raw_candidate(
        connection,
        source=source,
        prior_path=raw if prior_raw else None,
        candidate_path=raw_candidate,
        run_root=root,
    )
    raw_target, raw_audit = _publish_file(
        connection,
        source=source,
        run_root=root,
        target=raw,
        candidate_audit=raw_audit,
        prior=prior_raw,
        expected_relation=RAW_EXPECTED,
        check_cancel=check_cancel,
        raw_guard=lambda: None,
    )
    yield raw_target, raw_audit
    check_cancel()

    def raw_guard():
        if _hash_if_exists(raw) != raw_audit.file_sha256:
            raise ValueError("技术因子生成Silver期间对应Raw已改变")

    raw_guard()
    prior_silver = _hash_if_exists(silver)
    silver_audit = build_stk_factor_pro_silver_candidate(
        connection,
        verified_raw_path=raw,
        target_trade_date=source.identity.target_trade_date,
        candidate_path=silver_candidate,
        run_root=root,
    )
    raw_guard()
    yield _publish_file(
        connection,
        source=source,
        run_root=root,
        target=silver,
        candidate_audit=silver_audit,
        prior=prior_silver,
        expected_relation=SILVER_EXPECTED,
        check_cancel=check_cancel,
        raw_guard=raw_guard,
    )
