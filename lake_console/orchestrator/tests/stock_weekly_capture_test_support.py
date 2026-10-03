"""Offline source doubles; no real credentials, DB or Lake references."""

import time
from contextlib import contextmanager
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


class FakeCursor:
    def __init__(self, connection, name=None):
        self.connection = connection
        self.name = name
        self.itersize = None
        self.position = 0
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.connection.queries.append((query, params))
        if self.name and self.connection.blocked:
            while not self.connection.was_canceled:
                time.sleep(0.01)
            raise RuntimeError("query canceled")

    def fetchone(self):
        if "txid_current_snapshot" in self.query:
            return ("100:200:", "2026-10-03T00:00:00Z")
        return (self.connection.control_count,)

    def fetchmany(self, size):
        self.connection.fetch_sizes.append(size)
        result = self.connection.rows[self.position : self.position + size]
        self.position += len(result)
        return result

    def fetchall(self):
        raise AssertionError("full fetch forbidden")


class FakeConnection:
    def __init__(self, frame=None, control_count=None, blocked=False):
        self.rows = (frame if frame is not None else prod_frame()).values.tolist()
        self.control_count = len(self.rows) if control_count is None else control_count
        self.blocked = blocked
        self.queries = []
        self.sessions = []
        self.fetch_sizes = []
        self.was_canceled = False
        self.rollback_count = 0

    def set_session(self, **kwargs):
        assert not self.queries
        self.sessions.append(kwargs)

    def cursor(self, name=None):
        return FakeCursor(self, name)

    def cancel(self):
        self.was_canceled = True


class FakeResource:
    def __init__(self, connection=None):
        self.connection = connection or FakeConnection()
        self.connection_count = 0

    @contextmanager
    def connect_readonly_transaction(self):
        self.connection_count += 1
        try:
            yield self.connection
        finally:
            self.connection.rollback_count += 1


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
        prod_resource=FakeResource(FakeConnection(prod_frame("000001.SZ"))),
        progress=progress,
    )
