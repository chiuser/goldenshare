"""Offline source doubles; no real credentials, DB or Lake references."""

import time
from dataclasses import dataclass

import pandas as pd

from orchestrator.defs.run_contracts.stock_weekly import (
    ADJUSTED_WEEKLY_FIELDS,
    ProdWeeklyScope,
    ProdYearInventory,
    StockWeeklySource,
    WeeklyBudget,
)
from orchestrator.defs.stock_weekly_planner import freeze_prod_weekly_plan


def prod_plan(codes=("000005.SZ",), budget=None):
    budget = budget or WeeklyBudget()
    return freeze_prod_weekly_plan(
        ProdWeeklyScope(
            StockWeeklySource.PRIMARY_ADJUSTED,
            (ProdYearInventory(2020, codes, len(codes) * 52),),
            "reports/inventory.csv",
            "a" * 64,
            budget,
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
                *["10.0000"] * 8,
                "500.0000",
                "600.0000",
                None,
                None,
            ]
        ],
        columns=ADJUSTED_WEEKLY_FIELDS,
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
        return pd.DataFrame([{name: "offline" for name in fields}], columns=fields)


@dataclass
class SourceFailureWorker:
    """Raise synthetic exceptions in a real spawned child, without network IO."""

    mode: str

    def __call__(self, params, fields, max_rows):
        import json
        import os

        from requests import exceptions as request_errors

        from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
        from orchestrator.defs.tushare_errors import TushareResponseError

        secret = "synthetic-secret-token https://user:password@example.invalid/"
        if self.mode == "exit":
            os._exit(19)
        if self.mode == "decode":
            raise json.JSONDecodeError(secret, secret, 0)
        if self.mode == "arbitrary_type":
            raise type("synthetic-secret-token", (Exception,), {})(secret)
        if self.mode == "business":
            raise Exception("无权限/积分/频率/限流 " + secret)  # noqa: TRY002 -- Match the installed SDK's untyped business rejection.
        if self.mode == "row_budget":
            raise WeeklyCaptureError("unit_row_budget_exceeded")
        error_type = {
            "proxy": request_errors.ProxyError,
            "tls": request_errors.SSLError,
            "connect_timeout": request_errors.ConnectTimeout,
            "read_timeout": request_errors.ReadTimeout,
            "connection": request_errors.ConnectionError,
            "request": request_errors.RequestException,
            "requests_decode": request_errors.JSONDecodeError,
            "schema": TushareResponseError,
            "dependency": ImportError,
            "type": TypeError,
            "value": ValueError,
            "unknown": Exception,
            "capture_unknown": WeeklyCaptureError,
        }[self.mode]
        if self.mode == "requests_decode":
            raise error_type(secret, secret, 0)
        raise error_type(secret)


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


def adjusted_captured(tmp_path, frames, *, bootstrap_header=None):
    """Complete offline B0 inventory and real sealed receipts, including empty years."""
    import json
    from dataclasses import asdict, replace

    import duckdb

    from orchestrator.defs.bootstrap.stock_weekly_adj_bootstrap import (
        AdjustedWeeklyBootstrapGuard,
    )
    from orchestrator.defs.bootstrap.stock_weekly_capture import (
        WeeklyCaptureStore,
        capture_file_hash,
    )

    from .stock_weekly_adj_delivery_test_support import delivery_fixture

    frame = pd.concat(frames, ignore_index=True)
    first, last = min(frame.trade_date).strip()[:4], max(frame.trade_date).strip()[:4]
    source = StockWeeklySource.PRIMARY_ADJUSTED
    inventories = []
    root = tmp_path / "capture"
    root.mkdir(exist_ok=True)
    proof = root / "inventory.csv"
    csv = "source,year,ts_code,source_rows\n"
    for year in range(int(first) - 1, int(last) + 2):
        subset = frame[frame.trade_date.str.startswith(str(year))]
        codes = tuple(sorted(set(subset.ts_code)))
        inventories.append(ProdYearInventory(year, codes, len(subset)))
        for code in codes:
            csv += (
                f"{source.value},{year},{code},{len(subset[subset.ts_code == code])}\n"
            )
    proof.write_text(csv)
    original, _ = delivery_fixture()
    header = replace(
        original,
        record_kind="bootstrap_closed",
        header={**original.header, "bootstrap": True},
    )
    if bootstrap_header is not None:
        header = bootstrap_header
    path = root / "inventory.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "prod_weekly_inventory",
                "source": source.value,
                "bootstrap_boundary": asdict(header),
                "inventories": [asdict(i) for i in inventories],
                "snapshot": [{"readonly": "on", "isolation": "repeatable read"}],
                "empty_years": [i.year for i in inventories if not i.source_rows],
                "date_window": [
                    f"{inventories[0].year}-01-01",
                    f"{inventories[-1].year + 1}-01-01",
                ],
                "input_inventory": {
                    "path": str(proof),
                    "sha256": capture_file_hash(proof),
                },
            }
        )
    )
    plan = freeze_prod_weekly_plan(
        ProdWeeklyScope(source, tuple(inventories), str(path), capture_file_hash(path))
    )
    store = WeeklyCaptureStore(root, plan)
    receipts = []
    with store.locked(), duckdb.connect() as con:
        for unit in plan.units:
            subset = frame[
                frame.ts_code.isin(unit.sorted_codes)
                & frame.trade_date.str.startswith(str(unit.source_date_start.year))
            ]
            attempt = store.begin_attempt(unit)
            chunk = store.write_chunk(con, subset, unit, attempt, 0)
            receipt = store.seal(con, unit, [chunk], len(subset), {})
            receipt_path = store.unit_directory(unit) / "receipt.json"
            receipts.append(
                {
                    "unit_id": unit.unit_id,
                    "sha256": capture_file_hash(receipt_path),
                    "source_rows": receipt["source_rows"],
                }
            )
        # No remote reader is constructed or called in this isolated fixture.
        guard = AdjustedWeeklyBootstrapGuard(plan, reader=object())
        guard.seal(store, receipts, len(frame), cancel=lambda: False)
    return plan, root
