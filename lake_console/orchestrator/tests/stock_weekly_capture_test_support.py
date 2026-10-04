"""Offline source doubles; no real credentials, DB or Lake references."""

import time
from dataclasses import dataclass

import pandas as pd

from orchestrator.defs.run_contracts.stock_weekly import (
    ALTERNATE_WEEKLY_FIELDS,
    PRIMARY_WEEKLY_FIELDS,
    ProdWeeklyScope,
    ProdYearInventory,
    StockWeeklySource,
    WeeklyAvailability,
    WeeklyBudget,
    WeeklyCandidate,
    WeeklyHistoryScope,
)
from orchestrator.defs.stock_weekly_planner import (
    freeze_prod_weekly_plan,
    freeze_weekly_history_plan,
)


def prod_plan(codes=("000005.SZ",), budget=None):
    budget = budget or WeeklyBudget()
    return freeze_prod_weekly_plan(
        ProdWeeklyScope(
            StockWeeklySource.PRIMARY_UNADJUSTED,
            (ProdYearInventory(2020, codes, len(codes) * 52),),
            "reports/inventory.csv",
            "a" * 64,
            budget,
        )
    )


def weekly_plan(budget=None):
    budget = budget or WeeklyBudget(max_retries=0)
    return freeze_weekly_history_plan(
        WeeklyHistoryScope(
            "2020-01-03",
            "2020-12-25",
            (
                WeeklyCandidate(
                    "000005.SZ",
                    "2020-02-28",
                    WeeklyAvailability.AVAILABLE,
                    "reports/source.json",
                    "b" * 64,
                ),
            ),
            "reports/keys.csv",
            "c" * 64,
            budget=budget,
        )
    )


def prod_frame(code="000005.SZ", trade_date="20200228"):
    return pd.DataFrame(
        [
            [
                code,
                trade_date,
                trade_date,
                "week",
                "10.1234",
                "11.0000",
                "9.0000",
                None,
                "10.0000",
                "500.0000",
                "600.0000",
                None,
                None,
            ]
        ],
        columns=PRIMARY_WEEKLY_FIELDS,
        dtype=object,
    )


def alternate_frame():
    return pd.DataFrame(
        [
            [
                "000005.SZ",
                "20200228",
                10.0,
                10.0,
                11.0,
                9.0,
                None,
                None,
                None,
                500.0,
                600.0,
            ]
        ],
        columns=ALTERNATE_WEEKLY_FIELDS,
        dtype=object,
    )


@dataclass
class StaticWorker:
    mode: str = "ok"

    def __call__(self, params, fields, max_rows):
        if self.mode == "blocked":
            time.sleep(30)
        if self.mode == "failed":
            raise RuntimeError("secret-token-in-error")
        if self.mode == "empty":
            return pd.DataFrame(columns=fields, dtype=object)
        if self.mode == "zero_columns":
            return pd.DataFrame()
        return alternate_frame()


class FakePsqlExporter:
    def __init__(self, frame=None, control_count=None):
        self.frame = frame
        self.control_count = control_count
        self.calls = 0

    def export(self, unit, budget, attempt, cancel, progress, remaining_rows):
        import json

        from orchestrator.defs.bootstrap.stock_weekly_capture import (
            WeeklyCaptureError,
            capture_file_hash,
        )

        frame = (
            self.frame if self.frame is not None else prod_frame(unit.sorted_codes[0])
        )
        count = len(frame) if self.control_count is None else self.control_count
        self.calls += 1
        if count > unit.max_rows:
            raise WeeklyCaptureError("unit_row_budget_exceeded")
        if count > remaining_rows:
            raise WeeklyCaptureError("phase_row_budget_exceeded")
        path = attempt / "transport.csv"
        frame.to_csv(path, index=False, na_rep="\\N")
        control = attempt / "control.json"
        evidence = {
            "source_rows": count,
            "snapshot": "100:200:",
            "snapshot_at": "2026-10-03T00:00:00Z",
            "readonly": "on",
            "isolation": "repeatable read",
        }
        control.write_text(json.dumps(evidence))
        evidence["capture_artifacts"] = [
            {"path": str(p.relative_to(attempt.parent)), "sha256": capture_file_hash(p)}
            for p in (path, control)
        ]
        return path, evidence


def bind_plan_evidence(plan, tmp_path):
    import hashlib
    from dataclasses import replace

    path = tmp_path / "inventory.csv"
    path.write_text("offline frozen test inventory")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return replace(plan, evidence_ref=str(path), evidence_hash=digest)


def capture_then_exit(root):
    import os
    from pathlib import Path

    from orchestrator.defs.bootstrap.stock_weekly_history import capture_weekly_history

    plan = bind_plan_evidence(
        prod_plan(("000001.SZ", "000005.SZ"), budget=WeeklyBudget(prod_code_batch=1)),
        Path(root),
    )

    def progress(payload):
        if payload["completed_units"] == 1:
            os._exit(17)

    capture_weekly_history(
        plan,
        capture_root=Path(root),
        prod_exporter=FakePsqlExporter(prod_frame("000001.SZ")),
        progress=progress,
    )
