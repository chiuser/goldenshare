import json
from datetime import UTC, date, datetime, timedelta
from threading import Lock
from time import monotonic

import httpx

from src.biz.services.wealth.data_center.errors import DataCenterError
from src.foundation.config.announcement_archive import DataCenterPolicy

DAGSTER_GRAPHQL_URL = "http://127.0.0.1:3000/graphql"
SUMMARY_JOB = "daily_data_audit_summary_job"
SUMMARY_META = "data_audit_summary"
SUMMARY_STATUS_KEYS = ("complete", "gap", "pending", "not_applicable")
BOARD_RAW = "raw_tushare_dc_index"
BOARD_SILVER = "silver_dc_index"
_CONCEPT = "概念板块"
BOARD_CONFIRM_JOB = "daily_data_audit_board_confirm_job"
BOARD_RECHECK_JOB = "daily_data_audit_board_recheck_job"
_BOARD_OUTPUTS = {
    BOARD_CONFIRM_JOB: ("save_dc_index_standard", "dc_index_standard"),
    BOARD_RECHECK_JOB: ("recheck_dc_index", "dc_index_recheck"),
}
_ACTIVE_STATUSES = ["NOT_STARTED", "QUEUED", "STARTING", "STARTED", "SUSPENDED", "CANCELING"]
_TERMINAL_STATUSES = {"SUCCESS", "FAILURE", "CANCELED"}
_DAY_TAG = "audit/business_date"
_REVIEW_TAG = "audit/review_version"
# LLD §8 gives the recheck one shared budget through queueing and source requests.
_RECHECK_SECONDS = 600
_DG_READ_ERRORS = (httpx.HTTPError, TimeoutError, KeyError, TypeError, ValueError, StopIteration)

_FIND_RUN = """
query DataAuditSummaryRun($filter: RunsFilter!) {
  runsOrError(filter: $filter, limit: 1) {
    __typename
    ... on Runs { results { runId } }
  }
}
"""
_READ_SUMMARY = """
query DataAuditSummaryRecord($id: ID!) {
  logsForRun(runId: $id, limit: 32) {
    __typename
    ... on EventConnection {
      events {
        ... on ExecutionStepOutputEvent {
          stepKey
          metadataEntries { label ... on JsonMetadataEntry { jsonString } }
        }
      }
    }
  }
}
"""
_BOARD_RUNS = """
query DataAuditBoardRuns($confirm: RunsFilter!, $recheck: RunsFilter!) {
  confirm: runsOrError(filter: $confirm, limit: 1) {
    __typename
    ... on Runs { results { ...BoardRunFields } }
  }
  recheck: runsOrError(filter: $recheck, limit: 1) {
    __typename
    ... on Runs { results { ...BoardRunFields } }
  }
}
fragment BoardRunFields on Run { runId jobName status tags { key value } runConfig }
"""
_BOARD_RUN = """
query DataAuditBoardRun($id: ID!) {
  runOrError(runId: $id) {
    __typename
    ... on Run { runId jobName status tags { key value } runConfig }
  }
}
"""
_READ_BOARD_OUTPUT = """
query DataAuditBoardOutput($id: ID!, $cursor: String) {
  logsForRun(runId: $id, afterCursor: $cursor, limit: 32) {
    __typename
    ... on EventConnection {
      cursor
      hasMore
      events {
        ... on ExecutionStepOutputEvent {
          stepKey
          metadataEntries { label ... on JsonMetadataEntry { jsonString } }
        }
      }
    }
  }
}
"""
_LAUNCH_BOARD = """
mutation DataAuditBoardLaunch($executionParams: ExecutionParams!) {
  launchRun(executionParams: $executionParams) {
    __typename
    ... on LaunchRunSuccess { run { runId status } }
  }
}
"""


def day_response(day: date, state: str) -> dict:
    return {
        "state": state,
        "business_date": day.isoformat(),
        "observed_at": None,
        "generated_at": None,
        "summary_run_id": None,
        "summary": None,
        "rows": [],
        "can_operate": False,
    }


class DataAuditReader:
    def __init__(self, client: httpx.Client):
        self._client = client
        self._submit_lock = Lock()

    def _query(self, query: str, variables: dict, deadline: float) -> dict:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError
        response = self._client.post(
            DAGSTER_GRAPHQL_URL,
            json={"query": query, "variables": variables},
            timeout=remaining,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("errors"):
            raise ValueError("DG summary query failed")
        return body["data"]

    def read(self, day: date, summary_run_id: str | None = None, *, deadline: float | None = None) -> dict:
        if deadline is None:
            deadline = monotonic() + DataCenterPolicy().sql_seconds
        filters = {
            "pipelineName": SUMMARY_JOB,
            "statuses": ["SUCCESS"],
            "tags": [{"key": "audit/business_date", "value": day.isoformat()}],
        }
        if summary_run_id is not None:
            filters["runIds"] = [summary_run_id]
        try:
            runs = self._query(_FIND_RUN, {"filter": filters}, deadline)["runsOrError"]
            if runs["__typename"] != "Runs":
                return day_response(day, "unavailable")
            if not runs["results"]:
                return day_response(day, "not_generated")
            run_id = runs["results"][0]["runId"]
            event_log = self._query(_READ_SUMMARY, {"id": run_id}, deadline)["logsForRun"]
            record = next(
                entry["jsonString"]
                for event in event_log["events"]
                if event.get("stepKey") == "generate_data_audit_summary"
                for entry in event["metadataEntries"]
                if entry["label"] == SUMMARY_META
            )
            summary = json.loads(record)
            if summary["schema_version"] != 1 or summary["business_date"] != day.isoformat():
                return day_response(day, "unavailable")
            return {
                **day_response(day, "ready"),
                "summary_run_id": run_id,
                "observed_at": summary["observed_at"],
                "generated_at": summary["generated_at"],
                "summary": {key: summary["summary"][key] for key in SUMMARY_STATUS_KEYS},
                "rows": summary["rows"],
            }
        except _DG_READ_ERRORS:
            return day_response(day, "unavailable")

    def _board_runs(self, day: str, version: str, statuses: list[str], deadline: float) -> dict:
        tags = [{"key": _DAY_TAG, "value": day}, {"key": _REVIEW_TAG, "value": version}]
        jobs = {"confirm": BOARD_CONFIRM_JOB, "recheck": BOARD_RECHECK_JOB}
        data = self._query(_BOARD_RUNS, {
            action: {"pipelineName": job, "tags": tags, "statuses": statuses}
            for action, job in jobs.items()
        }, deadline)
        runs = {}
        for action, job in jobs.items():
            result = data[action]
            if result["__typename"] != "Runs":
                raise ValueError("DG board run lookup failed")
            if result["results"]:
                run = result["results"][0]
                if (run["jobName"], *_run_scope(run)) != (job, day, version) or run["status"] not in statuses:
                    raise ValueError("DG board run scope mismatch")
                runs[job] = run
        return runs

    def _board_output(self, run: dict, deadline: float) -> dict:
        job, run_id = run["jobName"], run["runId"]
        step, label = _BOARD_OUTPUTS[job]
        day, version = _run_scope(run)
        cursor = None
        while True:
            log = self._query(_READ_BOARD_OUTPUT, {"id": run_id, "cursor": cursor}, deadline)["logsForRun"]
            if log["__typename"] != "EventConnection":
                raise ValueError("DG board output lookup failed")
            for event in log["events"]:
                if event.get("stepKey") != step:
                    continue
                for entry in event.get("metadataEntries", ()):
                    if entry["label"] == label:
                        result = json.loads(entry["jsonString"])
                        if (result["business_date"], result["review_version"]) != (day, version):
                            raise ValueError("DG board output scope mismatch")
                        if job == BOARD_RECHECK_JOB and (
                            result["run_id"] != run_id or not isinstance(result["results"], list)
                            or not isinstance(result["has_confirmed_gap"], bool)
                        ):
                            raise ValueError("DG board recheck output invalid")
                        if job == BOARD_CONFIRM_JOB and (
                            result["version"] != run_id or not isinstance(result["boards"], list)
                        ):
                            raise ValueError("DG board standard output invalid")
                        return result
            if not log["hasMore"] or log["cursor"] == cursor:
                raise ValueError("DG board output missing")
            cursor = log["cursor"]

    def _board_review(self, day: date, asset_key: str, deadline: float) -> dict:
        if asset_key not in (BOARD_RAW, BOARD_SILVER):
            raise DataCenterError("board_asset_not_found", "该资产没有板块分类核查", 404)
        summary = self.read(day, deadline=deadline)
        if summary["state"] == "unavailable":
            raise _dg_unavailable()
        rows = {row["scope"]["asset_key"]: row for row in summary["rows"]}
        review = rows.get(BOARD_RAW, {}).get("board_review")
        if asset_key not in rows or not review:
            raise DataCenterError("board_review_not_found", "该日没有板块分类核查记录", 404)
        day_key, version = review["business_date"], review["review_version"]
        if day_key != day.isoformat():
            raise ValueError("DG board review scope mismatch")

        view = dict(review)
        if version is None:
            return {**view, "can_confirm": False}
        runs = self._board_runs(day_key, version, ["SUCCESS"], deadline)
        if BOARD_RECHECK_JOB in runs:
            view["recheck"] = self._board_output(runs[BOARD_RECHECK_JOB], deadline)
        if BOARD_CONFIRM_JOB in runs:
            standard = self._board_output(runs[BOARD_CONFIRM_JOB], deadline)
            reference = review["reference"]
            if (standard["raw_run_id"], standard["reference_version"]) != (
                review["raw_run_id"], reference["version"] if reference else None,
            ):
                raise ValueError("DG board standard inputs mismatch")
            view["standard"] = standard
            view.update(state="ready", reason=None)
        gap = (view["recheck"] or {}).get("has_confirmed_gap")
        if view["standard"] is None:
            if gap:
                view["reason"] = "confirmed_source_gap"
            elif view["reason"] == "confirmed_source_gap":
                view["reason"] = "manual_review"
        view["can_confirm"] = (
            asset_key == BOARD_RAW
            and (review["can_confirm"] or review["reason"] == "confirmed_source_gap")
            and view["standard"] is None and not gap
        )
        return view

    def board_review(self, day: date, asset_key: str) -> dict:
        try:
            return self._board_review(day, asset_key, monotonic() + DataCenterPolicy().sql_seconds)
        except _DG_READ_ERRORS as exc:
            raise _dg_unavailable() from exc

    def _find_board_run(self, run_id: str, deadline: float) -> dict:
        run = self._query(_BOARD_RUN, {"id": run_id}, deadline)["runOrError"]
        if run["__typename"] not in ("Run", "RunNotFoundError", "PipelineRunNotFoundError"):
            raise ValueError("DG board run lookup failed")
        if (run["__typename"] != "Run" or run["jobName"] not in _BOARD_OUTPUTS
                or run["runId"] != run_id or not all(_run_scope(run))):
            raise DataCenterError("board_run_not_found", "没有找到此板块核查任务", 404)
        return run

    def board_run(self, run_id: str) -> dict:
        deadline = monotonic() + DataCenterPolicy().sql_seconds
        try:
            run = self._find_board_run(run_id, deadline)
            day, version = _run_scope(run)
            status = run["status"]
            return {
                **_submission(run),
                "business_date": day,
                "review_version": version,
                "job_name": run["jobName"],
                "deadline": _recheck_deadline(run),
                "result": self._board_output(run, deadline) if status == "SUCCESS" else None,
                "error": {
                    "code": "board_run_failed",
                    "message": "本次核查或确认未完成，请刷新名单后查看",
                } if status == "FAILURE" else None,
            }
        except _DG_READ_ERRORS as exc:
            raise _dg_unavailable() from exc

    def submit_board(
        self, day: date, asset_key: str, *, review_version: str, requested_by: str,
        recheck: bool, retry_run_id: str | None = None,
    ) -> dict:
        if asset_key == BOARD_SILVER:
            raise DataCenterError("board_scope_invalid", "只允许操作东方财富板块分类 Raw", 422)
        deadline = monotonic() + DataCenterPolicy().sql_seconds
        if not self._submit_lock.acquire(timeout=DataCenterPolicy().sql_seconds):
            raise _dg_unavailable()
        try:
            view = self._board_review(day, asset_key, deadline)
            if view["review_version"] != review_version:
                raise DataCenterError("board_review_stale", "名单核查版本已变，请刷新后重试", 409)
            if recheck and (view["standard"] is not None or not any(
                board["category"] == _CONCEPT for board in (*view["added"], *view["removed"])
            )):
                raise DataCenterError("board_recheck_unavailable", "当前名单没有待核查差异", 409)
            if not recheck and not view["can_confirm"]:
                if (view["recheck"] or {}).get("has_confirmed_gap"):
                    raise DataCenterError("board_confirmed_gap", "源端已确认本地缺少板块，请先补齐", 409)
                raise DataCenterError("board_confirmation_unavailable", "当前版本不能生成标准集，请刷新后查看", 409)

            day_key = day.isoformat()
            job = BOARD_RECHECK_JOB if recheck else BOARD_CONFIRM_JOB
            if retry_run_id is not None:
                previous = self._find_board_run(retry_run_id, deadline)
                if (previous["jobName"], *_run_scope(previous)) != (job, day_key, review_version):
                    raise DataCenterError("board_retry_scope_invalid", "重试必须使用同日同版核查任务", 422)
                if previous["status"] not in _TERMINAL_STATUSES:
                    raise DataCenterError("board_operation_in_progress", "原核查任务尚未结束", 409)
                latest = view["recheck"]
                if not latest or latest["run_id"] != retry_run_id or not any(
                    item[endpoint]["status"] == "failed"
                    for item in latest["results"] for endpoint in ("classification", "member")
                ):
                    raise DataCenterError("board_retry_unavailable", "请从同版最近一次核查结果重试失败项", 409)

            active = self._board_runs(day_key, review_version, _ACTIVE_STATUSES, deadline)
            if job in active:
                return _submission(active[job])
            if active:
                raise DataCenterError("board_operation_in_progress", "该日该版本已有核查或确认任务在执行", 409)

            config = {"business_date": day_key, "review_version": review_version, "requested_by": requested_by}
            if view.get("used_history"):
                config["use_history"] = True
            if recheck:
                config["retry_run_id"] = retry_run_id
                config["deadline"] = (datetime.now(UTC) + timedelta(seconds=_RECHECK_SECONDS)).isoformat()
            step, _ = _BOARD_OUTPUTS[job]
            response = self._query(_LAUNCH_BOARD, {"executionParams": {
                "selector": {"repositoryLocationName": "orchestrator", "repositoryName": "__repository__", "jobName": job},
                "runConfigData": {"ops": {step: {"config": config}}},
                "executionMetadata": {"tags": [
                    {"key": _DAY_TAG, "value": day_key}, {"key": _REVIEW_TAG, "value": review_version},
                ]},
            }}, deadline)["launchRun"]
            if response["__typename"] != "LaunchRunSuccess":
                raise ValueError("DG board submission failed")
            run = response["run"]
            return {"run_id": run["runId"], "status": run["status"], **({"deadline": config["deadline"]} if recheck else {})}
        except _DG_READ_ERRORS as exc:
            raise _dg_unavailable() from exc
        finally:
            self._submit_lock.release()


def _run_scope(run: dict) -> tuple[str, str]:
    tags = {tag["key"]: tag["value"] for tag in run["tags"]}
    return tags.get(_DAY_TAG, ""), tags.get(_REVIEW_TAG, "")


def _recheck_deadline(run: dict) -> str | None:
    if run["jobName"] != BOARD_RECHECK_JOB:
        return None
    return run["runConfig"]["ops"]["recheck_dc_index"]["config"]["deadline"]


def _submission(run: dict) -> dict:
    response = {"run_id": run["runId"], "status": run["status"]}
    if run["jobName"] == BOARD_RECHECK_JOB:
        response["deadline"] = _recheck_deadline(run)
    return response


def _dg_unavailable() -> DataCenterError:
    return DataCenterError("board_dg_unavailable", "暂时无法读取或提交本机 DG 板块核查")
