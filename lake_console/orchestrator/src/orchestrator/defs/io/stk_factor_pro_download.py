"""Synchronous current-run day and historical downloads."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic as system_monotonic
from zoneinfo import ZoneInfo

import dagster as dg
from duckdb import Error as DuckDBError

from orchestrator.defs.checks.stk_factor_pro import (
    compare_factor_relations,
    factor_columns,
    factor_content_sha,
    factor_file_sha,
    require_factor_history_relation,
    require_factor_relation,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.stk_factor_pro_candidates import (
    DAY_SOURCE,
    build_stk_factor_pro_raw_batch,
    materialize_stk_factor_pro_day_source,
    release_stk_factor_pro_day_source,
    stk_factor_pro_http_rows,
)
from orchestrator.defs.io.stk_factor_pro_history import (
    _json_read,
    _json_write,
    _path,
    _prepare,
    _promote,
    read_stk_factor_pro_source_files,
    recheck_stk_factor_pro_history_inputs,
    require_stk_factor_pro_history_eligibility,
    resolve_stk_factor_pro_history_units,
    verify_stk_factor_pro_current_source,
    write_stk_factor_pro_source_complete,
    write_stk_factor_pro_source_files,
)
from orchestrator.defs.paths import stk_factor_pro_run_staging_root
from orchestrator.defs.run_contracts.stk_factor_pro import (
    STK_FACTOR_PRO_CANCEL_STATUS_POLL_SECONDS,
    STK_FACTOR_PRO_PROCESSING_VERSION,
    STK_FACTOR_PRO_SOURCE_COLUMNS,
    STK_FACTOR_PRO_TIMEZONE,
    ContractIdentity,
    HistoryEligibilityRecord,
    HistoryPlanRecord,
    RecordRef,
    RunIdentity,
    SourceCompleteRecord,
    SourceFileRecord,
    VerifiedDaySource,
    stk_factor_pro_files_manifest_digest,
    stk_factor_pro_history_input_digest,
    stk_factor_pro_schema_digest,
    stk_factor_pro_scope_digest,
    stk_factor_pro_unit_key,
)
from orchestrator.tushare_download import (
    DownloadControl,
    DownloadMode,
    DownloadStatus,
    DownloadTask,
    ObjectTimeRange,
    TimeRange,
    TushareDownloader,
)
from orchestrator.tushare_download.contract_registry import content_digest
from orchestrator.tushare_download.contracts.stk_factor_pro import (
    STK_FACTOR_PRO_CONTRACT,
)
from orchestrator.tushare_download.download_models import UnitResult
from orchestrator.tushare_download.task_input import FrozenTaskInput
from orchestrator.tushare_download.unit_planner import UnitPlanner


def _day_task(identity: RunIdentity) -> DownloadTask:
    return DownloadTask(
        "stk_factor_pro",
        DownloadMode.BY_POINT,
        points=(identity.target_trade_date.isoformat(),),
    )


def _day_digests(connection, identity, contract, count):
    projection = {
        "mode": int(DownloadMode.BY_POINT),
        "object_code": None,
        "point": identity.target_trade_date.isoformat(),
        "start_date": None,
        "end_date": None,
    }
    scope = content_digest(
        {
            "record_kind": "stk_factor_pro.scope",
            "record_version": 1,
            "value": {
                "phase": "day",
                "T": identity.target_trade_date.isoformat(),
                "units": [projection],
            },
        }
    )
    source_digest = content_digest(
        {
            "record_kind": "stk_factor_pro.day_source",
            "record_version": 1,
            "value": {
                "contract": {
                    "contract_name": contract.contract_name,
                    "contract_version": contract.contract_version,
                    "contract_content_digest": contract.contract_content_digest,
                    "processing_version": contract.processing_version,
                },
                "scope_digest": scope,
                "unit": projection,
                "source_row_count": count,
                "row_count": count,
                "schema_content_digest": stk_factor_pro_schema_digest("raw"),
                "content_sha256": factor_content_sha(connection, DAY_SOURCE),
            },
        }
    )
    return scope, source_digest


def require_stk_factor_pro_current_day_source(connection, source):
    if not isinstance(source, VerifiedDaySource) or source.raw_relation != DAY_SOURCE:
        raise TypeError("日发布必须接收当前内存的VerifiedDaySource")
    if source.contract != ContractIdentity(
        "stk_factor_pro",
        "1",
        content_digest(STK_FACTOR_PRO_CONTRACT),
        STK_FACTOR_PRO_PROCESSING_VERSION,
    ):
        raise ValueError("日发布当前合同不符")
    count, _ = require_factor_relation(
        connection,
        DAY_SOURCE,
        target_trade_date=source.identity.target_trade_date,
        layer="raw",
    )
    if count != len(source.unit_result.records) or _day_digests(
        connection, source.identity, source.contract, count
    ) != (source.scope_digest, source.day_source_digest):
        raise ValueError("日发布内存U已改变或不对应本次已验证日源")


def verify_stk_factor_pro_day_source(
    connection, *, identity, result, summary, contract
):
    expected_contract = ContractIdentity(
        "stk_factor_pro",
        "1",
        content_digest(STK_FACTOR_PRO_CONTRACT),
        STK_FACTOR_PRO_PROCESSING_VERSION,
    )
    if contract != expected_contract:
        raise ValueError("技术因子当前登记合同与日源身份不符")
    task = _day_task(identity)
    frozen = FrozenTaskInput(
        task.contract_name, task.mode, None, task.points, None, None, (), ()
    )
    expected_unit = UnitPlanner(frozen, STK_FACTOR_PRO_CONTRACT).next_unit()
    count = len(result.records)
    if (
        result.unit != expected_unit
        or result.termination.all_scopes_complete is not True
        or result.termination.accepted_scope_count != 1
    ):
        raise ValueError("技术因子日unit身份或终点不符")
    if (
        summary.status is not DownloadStatus.SUCCEEDED
        or summary.download_complete is not True
        or (summary.total_units, summary.completed_units, summary.delivered_units)
        != (1, 1, 1)
        or summary.row_count != count
        or summary.completed_row_count != count
        or result.statistics.row_count != count
        or not summary.task_id
        or summary.failure is not None
        or summary.cleanup_errors
        or any(
            type(value) is not int
            for value in (
                summary.total_units,
                summary.completed_units,
                summary.delivered_units,
                summary.row_count,
                summary.completed_row_count,
                result.statistics.row_count,
            )
        )
    ):
        raise ValueError("技术因子最终下载summary不完整或行数不符")
    try:
        materialize_stk_factor_pro_day_source(
            connection, result, identity.target_trade_date
        )
        scope, source_digest = _day_digests(connection, identity, contract, count)
        return VerifiedDaySource(
            identity, contract, result, summary, DAY_SOURCE, scope, source_digest
        )
    except BaseException as error:
        _release_failed_day(connection, error)
        raise


def _release_failed_day(connection, primary):
    try:
        release_stk_factor_pro_day_source(connection)
    except DuckDBError as cleanup:
        primary.add_note(f"日源清理同时失败：{type(cleanup).__name__}")


def download_stk_factor_pro_day(
    connection,
    *,
    identity,
    contract,
    downloader=None,
    control=None,
    check_cancel,
    on_progress=None,
):
    downloader = TushareDownloader.load() if downloader is None else downloader
    result = None
    try:
        with downloader.download(
            _day_task(identity), control=control, on_progress=on_progress
        ) as session:
            for unit in session:
                if result is not None:
                    raise ValueError("技术因子日请求只能交付一个unit")
                result = unit
        summary = session.summary
        if summary.task_id != session.task_id:
            raise ValueError("技术因子summary不属于当前下载会话")
        if result is None:
            raise ValueError("技术因子日请求未交付unit")
        check_cancel()
        return verify_stk_factor_pro_day_source(
            connection,
            identity=identity,
            result=result,
            summary=summary,
            contract=contract,
        )
    except BaseException as error:
        _release_failed_day(connection, error)
        raise


HISTORY_CURRENT_UNIT = "stk_factor_pro_history_current_unit"
HISTORY_SAVED_UNIT = "stk_factor_pro_history_saved_unit"
HISTORY_FRAME = "stk_factor_pro_history_unit_frame"


def _history_task(units):
    return DownloadTask(
        "stk_factor_pro",
        DownloadMode.BY_OBJECT_RANGE,
        object_ranges=tuple(
            ObjectTimeRange(
                unit.object_code,
                TimeRange(unit.start_date.isoformat(), unit.end_date.isoformat()),
            )
            for unit in units
        ),
    )


def _history_native_units(task):
    # Business projections are already closed/validated by history planning.
    # The actual session additionally applies its configured input capacity.
    frozen = FrozenTaskInput(
        task.contract_name, task.mode, None, None, None, task.object_ranges, (), ()
    )
    planner = UnitPlanner(frozen, STK_FACTOR_PRO_CONTRACT)
    try:
        units = []
        while (unit := planner.next_unit()) is not None:
            units.append(unit)
        return tuple(units)
    finally:
        planner.close()


def _release_history_unit(connection, primary=None):
    failures = []
    for release in (
        lambda: connection.execute(f"DROP VIEW IF EXISTS {HISTORY_SAVED_UNIT}"),
        lambda: connection.execute(f"DROP TABLE IF EXISTS {HISTORY_CURRENT_UNIT}"),
        lambda: connection.unregister(HISTORY_FRAME),
    ):
        try:
            release()
        except DuckDBError as cleanup:
            failures.append(cleanup)
    if failures:
        reported = primary if primary is not None else failures[0]
        for cleanup in failures:
            reported.add_note(f"历史unit清理同时失败：{type(cleanup).__name__}")
        if primary is None:
            raise reported


def _save_stk_factor_pro_history_unit(
    connection, *, root, identity, contract, projected, native, result
):
    if (
        not isinstance(result, UnitResult)
        or result.unit != native
        or result.termination.all_scopes_complete is not True
        or type(result.termination.accepted_scope_count) is not int
        or result.termination.accepted_scope_count != 1
        or type(result.statistics.row_count) is not int
        or result.statistics.row_count != len(result.records)
    ):
        raise ValueError("历史unit身份、完整终点或实际行数不对应本次规划")
    key = stk_factor_pro_unit_key(projected)
    relative = f"source/history/units/{key}.parquet"
    path = _path(root, identity, relative)
    # Refuse an old source path before conversion or any new file write.
    if path.exists():
        raise ValueError("历史unit源已存在，不接受旧源或断点续写")
    dates = tuple(
        projected.start_date + timedelta(days=index)
        for index in range((projected.end_date - projected.start_date).days + 1)
    )
    frame = build_stk_factor_pro_raw_batch(
        rows=stk_factor_pro_http_rows(result, STK_FACTOR_PRO_SOURCE_COLUMNS),
        source_fields=STK_FACTOR_PRO_SOURCE_COLUMNS,
        source="http",
        expected_dates=dates,
    )
    connection.register(HISTORY_FRAME, frame)
    primary = None
    try:
        projection = ", ".join(
            f'CAST("{name}" AS {"VARCHAR" if index < 2 else "DOUBLE"}) AS "{name}"'
            for index, name in enumerate(STK_FACTOR_PRO_SOURCE_COLUMNS)
        )
        connection.execute(
            f"CREATE TEMP TABLE {HISTORY_CURRENT_UNIT} AS SELECT {projection} FROM {HISTORY_FRAME}"
        )
        count, _ = require_factor_history_relation(
            connection,
            HISTORY_CURRENT_UNIT,
            object_code=projected.object_code,
            start_date=projected.start_date,
            end_date=projected.end_date,
        )
        nulls = ", ".join(
            f'count(*) FILTER (WHERE "{name}" IS NULL)'
            for name in STK_FACTOR_PRO_SOURCE_COLUMNS
        )
        actual_nulls = connection.execute(
            f"SELECT {nulls} FROM {HISTORY_CURRENT_UNIT}"
        ).fetchone()
        if count != len(result.records) or actual_nulls != tuple(
            int(frame[name].isna().sum()) for name in STK_FACTOR_PRO_SOURCE_COLUMNS
        ):
            raise ValueError("历史unit转换前后行数或NULL发生变化")
        temporary = _prepare(path)
        connection.execute(
            copy_query_to_parquet(
                f"SELECT {factor_columns()} FROM {HISTORY_CURRENT_UNIT} ORDER BY ts_code,trade_date",
                temporary,
            )
        )
        connection.execute(
            f"CREATE TEMP VIEW {HISTORY_SAVED_UNIT} AS SELECT * FROM {read_parquet(temporary, hive_partitioning=False)}"
        )
        saved_count, _ = require_factor_history_relation(
            connection,
            HISTORY_SAVED_UNIT,
            object_code=projected.object_code,
            start_date=projected.start_date,
            end_date=projected.end_date,
        )
        comparison = compare_factor_relations(
            connection, expected=HISTORY_CURRENT_UNIT, actual=HISTORY_SAVED_UNIT
        )
        if saved_count != count or any(
            (
                comparison.missing_key_count,
                comparison.unexpected_key_count,
                comparison.changed_row_count,
            )
        ):
            raise ValueError("历史unit源保存后全部业务字段对账不符")
        sha = factor_file_sha(temporary)
        # Do not leave a live view referencing a file about to be renamed.
        connection.execute(f"DROP VIEW {HISTORY_SAVED_UNIT}")
        _promote(temporary, path)
        if factor_file_sha(path) != sha:
            raise ValueError("历史unit最终源文件读回SHA不符")
        return SourceFileRecord(
            "history",
            key,
            native.unit_id,
            native.ordinal,
            int(native.mode),
            projected.object_code,
            None,
            projected.start_date,
            projected.end_date,
            len(result.records),
            count,
            relative,
            sha,
            count,
            stk_factor_pro_schema_digest("raw"),
            contract.contract_content_digest,
            datetime.now(ZoneInfo(STK_FACTOR_PRO_TIMEZONE)),
        )
    except BaseException as error:
        primary = error
        raise
    finally:
        # Only the converted table/temporary view survive frame unregistration;
        # neither is retained across units.
        _release_history_unit(connection, primary)


def _require_stk_factor_pro_history_summary(session, *, units, rows):
    summary = session.summary
    if (
        summary.task_id != session.task_id
        or not summary.task_id
        or summary.status is not DownloadStatus.SUCCEEDED
        or summary.download_complete is not True
        or (summary.total_units, summary.completed_units, summary.delivered_units)
        != (units, units, units)
        or (summary.row_count, summary.completed_row_count) != (rows, rows)
        or summary.failure is not None
        or summary.cleanup_errors
        or any(
            type(value) is not int
            for value in (
                summary.total_units,
                summary.completed_units,
                summary.delivered_units,
                summary.row_count,
                summary.completed_row_count,
            )
        )
    ):
        raise ValueError("历史下载会话最终summary不完整或不对应本次全部unit")


def download_stk_factor_pro_history(
    connection,
    *,
    identity,
    contract,
    plan,
    ranges,
    prior_results,
    eligibility,
    lake_root: Path,
    staging_root: Path,
    recheck_inputs,
    downloader=None,
    control=None,
    check_cancel,
    on_progress=None,
):
    """Save complete current-run units; never continue another run's download."""
    if not isinstance(identity, RunIdentity) or not isinstance(plan, HistoryPlanRecord):
        raise TypeError("历史下载必须接收冻结执行身份及完整计划")
    if plan.identity != identity or plan.contract != contract:
        raise ValueError("历史下载必须使用当前run身份及同一完整契约计划")
    require_stk_factor_pro_history_eligibility(plan, eligibility)
    units = resolve_stk_factor_pro_history_units(
        connection,
        plan=plan,
        ranges=ranges,
        prior_results=prior_results,
        staging_root=staging_root,
    )
    if not units:
        raise ValueError("无待下载历史unit，不创建零unit任务")
    root = stk_factor_pro_run_staging_root(
        staging_root, identity.creator_run_id, identity.target_trade_date.isoformat()
    )
    source_root = _path(root, identity, "source/history")
    if source_root.exists():
        raise ValueError("当前run已有历史源目录，请创建完整重新下载的新任务")
    saved_eligibility = _path(root, identity, "history-eligibility.json")
    if saved_eligibility.exists():
        if _json_read(saved_eligibility, HistoryEligibilityRecord) != eligibility:
            raise ValueError("当前run历史资格记录与本次已核事实不符")
    else:
        _json_write(root, identity, "history-eligibility.json", eligibility)
    recheck_stk_factor_pro_history_inputs(
        connection,
        plan=plan,
        ranges=ranges,
        expected_units=units,
        lake_root=lake_root,
        recheck_inputs=recheck_inputs,
    )
    check_cancel()
    task = _history_task(units)
    native_units = _history_native_units(task)
    if len(native_units) != len(units):
        raise ValueError("历史组件planner未生成本次完整范围")
    downloader = TushareDownloader.load() if downloader is None else downloader
    files = []
    try:
        with downloader.download(
            task, control=control, on_progress=on_progress
        ) as session:
            for result in session:
                index = len(files)
                if index >= len(units):
                    raise ValueError("历史下载交付了规划之外的额外unit")
                check_cancel()
                files.append(
                    _save_stk_factor_pro_history_unit(
                        connection,
                        root=root,
                        identity=identity,
                        contract=contract,
                        projected=units[index],
                        native=native_units[index],
                        result=result,
                    )
                )
                del result
                check_cancel()
        if len(files) != len(units):
            raise ValueError("历史下载未交付全部预期unit")
        _require_stk_factor_pro_history_summary(
            session, units=len(units), rows=sum(file.file_rows for file in files)
        )
        check_cancel()
        files = tuple(sorted(files, key=lambda file: file.unit_key))
        manifest = write_stk_factor_pro_source_files(
            root,
            connection=connection,
            identity=identity,
            contract=contract,
            files=files,
        )
        if (
            read_stk_factor_pro_source_files(
                root,
                manifest,
                connection=connection,
                identity=identity,
                contract=contract,
            )
            != files
        ):
            raise ValueError("当前run历史manifest保存读回不一致")
        scope = stk_factor_pro_scope_digest(
            "history", identity.target_trade_date, units
        )
        record = SourceCompleteRecord(
            1,
            identity,
            "history",
            contract,
            RecordRef(
                identity.creator_run_id,
                "history-plan.json",
                factor_file_sha(root / "history-plan.json"),
            ),
            plan.history_plan_digest,
            plan.revision,
            plan.origin_history_plan_digest,
            plan.origin_history_ranges_digest,
            stk_factor_pro_history_input_digest(identity, contract, units, ranges),
            scope,
            units,
            manifest,
            stk_factor_pro_files_manifest_digest(scope, files),
            len(units),
            datetime.now(ZoneInfo(STK_FACTOR_PRO_TIMEZONE)),
        )
        write_stk_factor_pro_source_complete(root, record)
        return verify_stk_factor_pro_current_source(
            root,
            record,
            connection=connection,
            current_run_id=identity.creator_run_id,
            expected_units=units,
        )
    except BaseException as error:
        _release_history_unit(connection, error)
        raise


def build_stk_factor_pro_run_control(
    instance,
    *,
    identity,
    phase,
    monotonic=system_monotonic,
):
    if phase not in ("day", "history"):
        raise ValueError("技术因子取消检查阶段错误")
    checked_at = None
    cancelled = False

    def read(force=False):
        nonlocal checked_at, cancelled
        now = monotonic()
        if cancelled:
            return True
        if (
            not force
            and checked_at is not None
            and now - checked_at < STK_FACTOR_PRO_CANCEL_STATUS_POLL_SECONDS
        ):
            return False
        try:
            run = instance.get_run_by_id(identity.creator_run_id)
            if run is None or run.run_id != identity.creator_run_id:
                raise ValueError("当前任务不存在或身份不符")
            if run.status not in (
                dg.DagsterRunStatus.STARTING,
                dg.DagsterRunStatus.STARTED,
                dg.DagsterRunStatus.CANCELING,
                dg.DagsterRunStatus.CANCELED,
            ):
                raise ValueError("当前任务状态不允许下载")
        except Exception as error:
            raise dg.Failure(
                "无法读取技术因子当前任务状态，已停止。",
                allow_retries=False,
                metadata={
                    "goldenshare/failure_phase": phase,
                    "goldenshare/retryable": False,
                    "goldenshare/source_error_code": None,
                },
            ) from error
        checked_at = now
        cancelled = run.status in (
            dg.DagsterRunStatus.CANCELING,
            dg.DagsterRunStatus.CANCELED,
        )
        return cancelled

    def check_cancel():
        if read(force=True):
            raise dg.Failure(
                "技术因子任务已取消。",
                allow_retries=False,
                metadata={
                    "goldenshare/failure_phase": phase,
                    "goldenshare/retryable": False,
                    "goldenshare/source_error_code": None,
                },
            )

    return DownloadControl(is_cancelled=read), check_cancel
