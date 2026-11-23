"""Save board standards and run the bounded source review in the existing queue."""

import re
from datetime import date, datetime, timedelta
from time import sleep

import dagster as dg

from orchestrator.defs.daily_data_audit.dc_index_review import (
    BOARD_RECHECK_META,
    BOARD_STANDARD_META,
    BUSINESS_DATE_TAG,
    CONCEPT,
    REVIEW_VERSION_TAG,
    SHANGHAI,
    read_board_review_for_job,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_MAX_ELAPSED_MS,
    DC_BOARD_MAX_REQUESTS_PER_PARTITION,
    DC_INDEX_PAGE_LIMIT,
    DC_MEMBER_MIN_REQUEST_INTERVAL_SECONDS,
    DC_MEMBER_PAGE_LIMIT,
    is_dc_index_placeholder,
)
from orchestrator.tushare_download.contracts.dc_board_review import (
    DC_INDEX_REVIEW_CONTRACT,
    DC_MEMBER_REVIEW_CONTRACT,
)
from orchestrator.tushare_download.download_api import TushareDownloader
from orchestrator.tushare_download.download_errors import (
    DownloadCancelled,
    DownloadError,
)
from orchestrator.tushare_download.download_models import (
    DownloadControl,
    DownloadMode,
    DownloadProgressEvent,
    DownloadStatus,
    DownloadTask,
)

# TushareDownloader uses ConfigurationSnapshot's fixed per-call HTTP timeout.
_REQUEST_TIMEOUT = timedelta(seconds=45)
_REVIEW_WINDOW = timedelta(milliseconds=DC_BOARD_MAX_ELAPSED_MS)


class SaveDcIndexStandardConfig(dg.Config):
    business_date: str
    review_version: str | None = None
    requested_by: str
    use_history: bool = False


class RecheckDcIndexConfig(dg.Config):
    business_date: str
    review_version: str
    retry_run_id: str | None = None
    deadline: str
    requested_by: str | None = None
    use_history: bool = False


def _current_review(context, day, requested_version, *, use_history=False):
    try:
        review = read_board_review_for_job(
            context.instance, day, use_history=use_history
        )
    except ValueError as error:
        raise dg.Failure(str(error)) from error
    version = review["review_version"]
    if version is None:
        raise dg.Failure(
            "参照标准集缺失"
            if review["state"] == "reference_missing"
            else "缺少已通过且可对应当日 Raw 发布的板块名单"
        )
    if use_history and requested_version is None:
        if review["reference"] is not None and (review["added"] or review["removed"]):
            raise dg.Failure("板块名单有增减，请使用当前核查版本确认")
    elif version != requested_version:
        raise dg.Failure("板块名单或参照标准集已变化，请重新打开核查")
    context.instance.add_run_tags(
        context.run_id,
        {
            BUSINESS_DATE_TAG: day.isoformat(),
            REVIEW_VERSION_TAG: version,
        },
    )
    return review


@dg.op(out=dg.Out(dg.Nothing))
def save_dc_index_standard(
    context: dg.OpExecutionContext,
    config: SaveDcIndexStandardConfig,
) -> None:
    day = date.fromisoformat(config.business_date)
    review = _current_review(
        context,
        day,
        config.review_version,
        use_history=config.use_history,
    )
    if review["standard"] is not None:
        raise dg.Failure("当天同版标准集已生成")
    if not review["can_confirm"]:
        raise dg.Failure("Tushare 已确认本地板块名单有缺口，补齐后才能生成标准集")
    reference = review["reference"]
    context.add_output_metadata(
        {
            BOARD_STANDARD_META: dg.MetadataValue.json(
                {
                    "business_date": day.isoformat(),
                    "version": context.run_id,
                    "review_version": review["review_version"],
                    "raw_run_id": review["raw_run_id"],
                    "raw_fingerprint": review["raw_fingerprint"],
                    "reference_version": reference["version"] if reference else None,
                    "boards": review["current"],
                    "requested_by": config.requested_by,
                    "confirmed_at": datetime.now(SHANGHAI).isoformat(),
                }
            ),
        }
    )


class _RecheckBudget:
    def __init__(self, deadline):
        self.deadline = deadline
        self.request_count = 0
        self.retry_count = 0

    def expired(self):
        return datetime.now(SHANGHAI) >= self.deadline

    def next_request_error(self, session_requests=0, *, delay=0):
        if self.request_count + session_requests >= DC_BOARD_MAX_REQUESTS_PER_PARTITION:
            return "已到本轮源端请求数上限"
        if (
            datetime.now(SHANGHAI) + timedelta(seconds=delay) + _REQUEST_TIMEOUT
            > self.deadline
        ):
            return "核查超时，剩余时间不足以发起请求"
        return None

    def before_request(self, session_requests=0, *, space_requests=False):
        delay = DC_MEMBER_MIN_REQUEST_INTERVAL_SECONDS if space_requests else 0
        reason = self.next_request_error(session_requests, delay=delay)
        if reason is None and space_requests:
            sleep(delay)
            reason = self.next_request_error(session_requests)
        return reason


def _checked_rows(result, day, code, contract):
    expected_fields = set(contract.field_names)
    if not result.observed_field_sets or any(
        set(fields) != expected_fields for fields in result.observed_field_sets
    ):
        raise ValueError("源端返回字段不符合合同")
    rows = [record.as_mapping() for record in result.records]
    day_key = day.strftime("%Y%m%d")
    if any((row["trade_date"], row["ts_code"]) != (day_key, code) for row in rows):
        raise ValueError("源端返回了其他日期或板块")
    if contract is DC_INDEX_REVIEW_CONTRACT:
        if len(rows) > 1 or any(
            row["idx_type"] != CONCEPT
            or not isinstance(row["name"], str)
            or not row["name"].strip()
            for row in rows
        ):
            raise ValueError("源端返回重复或无效的概念板块分类")
        return [
            {"category": row["idx_type"], "code": row["ts_code"], "name": row["name"]}
            for row in rows
            if not is_dc_index_placeholder(row)
        ]
    codes = [row["con_code"] for row in rows]
    if len(codes) != len(set(codes)) or any(
        not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code)
        for code in codes
    ):
        raise ValueError("源端返回重复或无效的成分代码")
    return rows


def _source_result(status, *, count=None, message=None, board=None):
    result = {
        "status": status,
        "count": count,
        "message": message,
        "checked_at": datetime.now(SHANGHAI).isoformat(),
    }
    if board is not None:
        result["board"] = board
    return result


def _request_source(downloader, contract, day, code, budget):
    reason = budget.before_request(space_requests=bool(budget.request_count))
    if reason:
        return _source_result("failed", message=reason)
    page_limit = (
        DC_INDEX_PAGE_LIMIT
        if contract is DC_INDEX_REVIEW_CONTRACT
        else DC_MEMBER_PAGE_LIMIT
    )
    task = DownloadTask(
        contract_name=contract.contract_name,
        mode=DownloadMode.BY_OBJECT_POINT,
        objects=(code,),
        points=(day.isoformat(),),
        filters={"idx_type": CONCEPT} if contract is DC_INDEX_REVIEW_CONTRACT else None,
    )

    def next_page_or_retry(progress):
        nonlocal reason
        retry = progress.event == DownloadProgressEvent.RETRY_SCHEDULED
        next_page = (
            progress.event == DownloadProgressEvent.PAGE_COMPLETED
            and progress.page_row_count == page_limit
        )
        if retry:
            reason = budget.next_request_error(
                progress.request_count,
                delay=progress.retry_delay_seconds,
            )
        elif next_page:
            reason = budget.before_request(
                progress.request_count, space_requests=next_page
            )
        if reason:
            raise DownloadCancelled()

    session = downloader.download(
        task,
        control=DownloadControl(is_cancelled=budget.expired),
        on_progress=next_page_or_retry,
    )
    try:
        with session:
            rows = _checked_rows(next(session), day, code, contract)
        summary = session.summary
        if summary.status != DownloadStatus.SUCCEEDED or not summary.download_complete:
            raise ValueError("源端分页未完整返回")
    except DownloadError as error:
        if error.code.name == "CANCELLED" and not reason:
            reason = "核查超时"
        return _source_result("failed", message=reason or str(error))
    except ValueError as error:
        return _source_result("failed", message=str(error))
    finally:
        budget.request_count += session.summary.request_count
        budget.retry_count += session.summary.retry_count
    return _source_result(
        "success" if rows else "not_returned",
        count=len(rows),
        board=rows[0] if rows and contract is DC_INDEX_REVIEW_CONTRACT else None,
    )


@dg.op(out=dg.Out(dg.Nothing))
def recheck_dc_index(
    context: dg.OpExecutionContext, config: RecheckDcIndexConfig
) -> None:
    day = date.fromisoformat(config.business_date)
    deadline = datetime.fromisoformat(config.deadline)
    if deadline.tzinfo is None:
        raise dg.Failure("核查截止时间必须包含时区")
    review = _current_review(context, day, config.review_version, use_history=config.use_history)
    if review["standard"]:
        raise dg.Failure("当天同版标准集已生成")
    differences = {
        board["code"]: board
        for board in (*review["added"], *review["removed"])
        if board["category"] == CONCEPT
    }
    if not differences:
        raise dg.Failure("当天没有需要复核的概念板块差异")
    latest = review["recheck"]
    current_run = context.instance.get_run_record_by_id(context.run_id)
    if latest:
        previous_run = context.instance.get_run_record_by_id(latest["run_id"])
        completed_at = (
            previous_run.end_time or previous_run.update_timestamp.timestamp()
        )
        if completed_at > current_run.create_timestamp.timestamp():
            raise dg.Failure("相同版本的核查已在排队期间完成")
    if config.retry_run_id and (not latest or config.retry_run_id != latest["run_id"]):
        raise dg.Failure("请按同版最近一次核查结果重试失败项")
    prior = {item["code"]: item for item in latest["results"]} if latest else {}
    retry = bool(config.retry_run_id)
    if retry and not any(
        item[endpoint]["status"] == "failed"
        for item in prior.values()
        for endpoint in ("classification", "member")
    ):
        raise dg.Failure("该次核查没有失败项")
    budget = _RecheckBudget(
        min(deadline, current_run.create_timestamp + _REVIEW_WINDOW)
    )
    downloader = None
    configuration_error = None
    if budget.next_request_error() is None:
        try:
            downloader = TushareDownloader.load()
        except DownloadError as error:
            configuration_error = str(error)
    current_codes = {
        board["code"] for board in review["current"] if board["category"] == CONCEPT
    }
    results = []
    for code in sorted(differences):
        previous = prior.get(code, {})
        item = {"code": code, "name": differences[code]["name"]}
        for endpoint, contract in (
            ("classification", DC_INDEX_REVIEW_CONTRACT),
            ("member", DC_MEMBER_REVIEW_CONTRACT),
        ):
            preceding = previous.get(endpoint)
            if retry and preceding["status"] != "failed":
                item[endpoint] = preceding
                continue
            reason = configuration_error or budget.next_request_error()
            result = (
                _source_result("failed", message=reason)
                if reason
                else _request_source(downloader, contract, day, code, budget)
            )
            if result["status"] == "failed" and preceding is not None:
                last_successful = (
                    preceding.get("last_successful_result")
                    if preceding["status"] == "failed"
                    else preceding
                )
                if last_successful is not None:
                    result["last_successful_result"] = last_successful
            item[endpoint] = result
        classification = item["classification"]
        effective_classification = (
            classification.get("last_successful_result", {})
            if classification["status"] == "failed"
            else classification
        )
        item["confirmed_gap"] = (
            effective_classification.get("status") == "success"
            and code not in current_codes
        )
        results.append(item)
    context.add_output_metadata(
        {
            BOARD_RECHECK_META: dg.MetadataValue.json(
                {
                    "business_date": day.isoformat(),
                    "review_version": review["review_version"],
                    "run_id": context.run_id,
                    "results": results,
                    "has_confirmed_gap": any(item["confirmed_gap"] for item in results),
                    "request_count": budget.request_count,
                    "retry_count": budget.retry_count,
                    "checked_at": datetime.now(SHANGHAI).isoformat(),
                }
            ),
        }
    )


@dg.job
def daily_data_audit_board_confirm_job():
    save_dc_index_standard()


@dg.job
def daily_data_audit_board_recheck_job():
    recheck_dc_index()
