"""Independent LLD12.5 partial historical receipt reproduction; temporary resources only.

Run from lake_console/orchestrator with its existing .venv Python and PYTHONPATH=src:.
The actual test producer creates two tiny frequencies and actual SQLite SDK events.
The only replaced boundary is HTTP via the existing literal 21-field test sample.
"""

import json
from pathlib import Path

from orchestrator.defs.bootstrap.stock_period_history import replay_events
from orchestrator.defs.io import stock_period_raw as raw
from tests.test_stock_period_delivery_confirmation import (
    _confirm,
    _event_count,
    _scenario,
)


def forbid_event(*args, **kwargs):
    raise AssertionError("historical confirmation must not emit a new business event")


record = {
    "claim": "LLD12.5 promises week-only receipt supplementation without closing a two-frequency batch",
    "code": "stock_period_history.py:567-584",
    "lld": "dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md:1374",
    "formal_resources_accessed": False,
}

with _scenario(frequencies=("week", "month")) as case:
    run = Path(case["old"]["path"])
    owned_directory = case["root"].parent
    before_events = _event_count(case["instance"])
    before_requests = len(case["requests"])
    before_daily = (case["staging"] / "stock_period/daily.json").read_bytes()
    before_manifest = (run / "manifest.json").read_bytes()
    before_complete = (run / "complete.json").read_bytes()
    before_current = raw.file_version(case["old"]["files"][0]["target"])
    proof = _confirm(case, allowed_frequencies={"week"})
    record["confirmation"] = {
        key: proof[key]
        for key in ("events_complete", "historical_only", "reason", "allowed_frequencies")
    }
    record["confirmed_files"] = [list(key) for key in proof["file_evidence"]]
    record["week_successor_count"] = len(
        proof["file_evidence"][("week", "2026-10-23")]["successors"]
    )
    try:
        result = replay_events(
            run,
            root=case["root"],
            staging=case["staging"],
            confirm_delivery=lambda _: _confirm(case, allowed_frequencies={"week"}),
            events=forbid_event,
            completion_events=forbid_event,
        )
        record["replay"] = {"returned": True, "events_complete": result["events_complete"]}
    except Exception as error:
        record["replay"] = {"returned": False, "type": type(error).__name__, "error": str(error)}
    record.update(
        phase=raw.read_json(run / "manifest.json")["phase"],
        week_cp_exists=(run / "events/week/2026-10-23.json").exists(),
        month_cp_exists=(run / "events/month/2026-10.json").exists(),
        pending_preserved=(case["staging"] / "stock_period/daily.json").read_bytes() == before_daily,
        manifest_preserved=(run / "manifest.json").read_bytes() == before_manifest,
        complete_preserved=(run / "complete.json").read_bytes() == before_complete,
        current_file_preserved=raw.file_version(case["old"]["files"][0]["target"]) == before_current,
        new_source_requests=len(case["requests"]) - before_requests,
        new_sdk_events=_event_count(case["instance"]) - before_events,
    )

record["temporary_resources_removed"] = not owned_directory.exists()
assert record["replay"] == {
    "returned": False,
    "type": "ValueError",
    "error": "period_committed_file_changed",
}
assert record["week_successor_count"] == 1
assert record["confirmation"]["historical_only"] is True
assert record["confirmation"]["events_complete"] is False
assert record["week_cp_exists"] is False
assert record["new_sdk_events"] == record["new_source_requests"] == 0
assert record["temporary_resources_removed"]
output = Path("/private/tmp/dg-period-independent-audit-20261028/partial-week-history.json")
output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(record, ensure_ascii=False))
