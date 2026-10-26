"""One synchronous day download; source rows live only in this call."""

from __future__ import annotations

from time import monotonic as system_monotonic

import dagster as dg
from duckdb import Error as DuckDBError

from orchestrator.defs.checks.stk_factor_pro import (
    factor_content_sha,
    require_factor_relation,
)
from orchestrator.defs.io.stk_factor_pro_candidates import (
    DAY_SOURCE,
    materialize_stk_factor_pro_day_source,
    release_stk_factor_pro_day_source,
)
from orchestrator.defs.run_contracts.stk_factor_pro import (
    STK_FACTOR_PRO_CANCEL_STATUS_POLL_SECONDS,
    STK_FACTOR_PRO_PROCESSING_VERSION,
    ContractIdentity,
    RunIdentity,
    VerifiedDaySource,
    stk_factor_pro_schema_digest,
)
from orchestrator.tushare_download import (
    DownloadControl,
    DownloadMode,
    DownloadStatus,
    DownloadTask,
    TushareDownloader,
)
from orchestrator.tushare_download.contract_registry import content_digest
from orchestrator.tushare_download.contracts.stk_factor_pro import (
    STK_FACTOR_PRO_CONTRACT,
)
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
