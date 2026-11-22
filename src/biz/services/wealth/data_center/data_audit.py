import json
from datetime import date
from time import monotonic

import httpx

from src.foundation.config.announcement_archive import DataCenterPolicy

DAGSTER_GRAPHQL_URL = "http://127.0.0.1:3000/graphql"
SUMMARY_JOB = "daily_data_audit_summary_job"
SUMMARY_META = "data_audit_summary"
SUMMARY_STATUS_KEYS = ("complete", "gap", "pending", "not_applicable")

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

    def read(self, day: date, summary_run_id: str | None = None) -> dict:
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
        except (httpx.HTTPError, TimeoutError, KeyError, TypeError, ValueError, StopIteration):
            return day_response(day, "unavailable")
