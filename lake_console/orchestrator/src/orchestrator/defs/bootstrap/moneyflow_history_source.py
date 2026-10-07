"""Bounded, cancellable COPY through the existing Prod read-only psql entry."""

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    MoneyflowHistoryPlan,
    moneyflow_history_export_sql,
)
from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_directory
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_STREAM_BYTES,
    MoneyflowContractError,
)


@dataclass(frozen=True)
class MoneyflowHistoryCopyRequest:
    plan: MoneyflowHistoryPlan
    unit_id: int
    sql_path: Path
    after_key: tuple[str, str] | None = None
    through_key: tuple[str, str] | None = None

    def sql(self) -> str:
        return moneyflow_history_export_sql(
            self.plan,
            self.unit_id,
            after_key=self.after_key,
            through_key=self.through_key,
        )


class PsqlMoneyflowHistorySource:
    """No arbitrary SQL, environment file, DSN, or target table arguments."""

    def copy(self, request: MoneyflowHistoryCopyRequest, sink, check) -> None:
        statement = request.sql()
        sql_path = request.sql_path
        if sql_path.name != "source.sql" or sql_path.is_symlink():
            raise MoneyflowContractError("history_sql_path")
        moneyflow_candidate_directory(
            sql_path.parent, "source", request.plan.cutoff, dataset=request.plan.dataset
        )
        check()
        with sql_path.open("x", encoding="utf8") as handle:
            handle.write(statement)
        repo_root = Path(__file__).resolve().parents[6]
        command = [
            "bash",
            "scripts/psql-remote.sh",
            "--env-file",
            str(repo_root / ".env.web.local"),
            "-f",
            str(sql_path),
            "--",
            "-q",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        _copy_process(command, repo_root, sink, check)


def _copy_process(command, cwd, sink, check) -> None:
    """Drain both pipes without whole-output buffering; never expose stderr."""
    check()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map() or process.poll() is None:
                check()
                for key, _ in selector.select(timeout=0.2):
                    chunk = os.read(
                        key.fileobj.fileno(), MONEYFLOW_HISTORY_STREAM_BYTES
                    )
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.data == "stdout":
                        sink.write(chunk)
                    check()
            if process.wait() != 0:
                raise MoneyflowContractError("history_source_failed")
            check()
    finally:
        # A shell may already have exited while its psql-equivalent child lives.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        process.stdout.close()
        process.stderr.close()
