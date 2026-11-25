"""Prepare and publish approved historical revisions to stock adjustment factors."""

from __future__ import annotations

import fcntl
import json
import math
import os
from collections.abc import Callable, Collection, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import mkdtemp
from uuid import UUID
from zoneinfo import ZoneInfo

import pandas as pd

from orchestrator.defs.duckdb_connection import (
    DEFAULT_DUCKDB_CONNECTION_SETTINGS,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import (
    adj_factor_normalized_select,
    adj_factor_retained_stock_select,
    duckdb_string,
    read_parquet,
    silver_adj_factor_select_from_relations,
)
from orchestrator.defs.io.adj_factor_silver_publication import (
    _check_path,
    _check_roots,
    _checkpoint,
    _sha256,
    _stable_identity,
    file_identity,
)
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.adj_factor import (
    ADJ_FACTOR_RETIRED_RETENTION_START_DATE,
)
from orchestrator.defs.stock_factor_price_checks import (
    adj_factor_partition_allowed_status,
    audit_adj_factor_candidate_rules,
)

FIELDS = ("ts_code", "trade_date", "adj_factor")
PAGE_SIZE = 6000
LAYERS = ("raw", "silver")
SHANGHAI = ZoneInfo("Asia/Shanghai")
PageReader = Callable[[str], Iterable[tuple[int, list[dict]]]]


class AdjFactorHistoryRefreshError(ValueError):
    """A revision cannot be prepared, published or verified against its inputs."""


def _noop() -> None:
    pass


def _no_progress(_record: dict) -> None:
    pass


def _json(path: Path) -> dict:
    _check_path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _identity(path: Path) -> dict:
    _check_path(path)
    identity = file_identity(path)
    if not path.is_file() or identity is None:
        raise AdjFactorHistoryRefreshError(f"Missing input: {path}")
    return identity


def _assert_identity(path: Path, expected: dict) -> None:
    if _identity(path) != expected:
        raise AdjFactorHistoryRefreshError(f"File changed since preparation: {path}")


def _fingerprint(path: Path) -> dict:
    identity = _identity(path)
    digest = _sha256(path)
    _assert_identity(path, identity)
    return {"identity": identity, "sha256": digest}


def _assert_artifact(path: Path, expected: dict, *, moved: bool = False) -> None:
    current = _identity(path)
    match = _stable_identity if moved else lambda value: value
    if match(current) != match(expected["identity"]) or _sha256(path) != expected["sha256"]:
        raise AdjFactorHistoryRefreshError(f"Sealed artifact changed: {path}")


@contextmanager
def _operation(lake: Path, staging: Path, operation_id: str) -> Iterator[Path]:
    if str(UUID(operation_id)) != operation_id:
        raise AdjFactorHistoryRefreshError("Operation ID must be a canonical UUID")
    _check_roots(lake, staging)
    parent = staging / "adj_factor" / "history_refresh"
    run = parent / operation_id
    lock_path = parent / "writer.lock"
    _check_path(run)
    _check_path(lock_path)
    parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield run


def _connect(run: Path):
    settings = replace(DEFAULT_DUCKDB_CONNECTION_SETTINGS, temp_directory=run)
    return connect_configured_duckdb(settings, temp_policy="existing_no_spill")


def _parse_day(value: str) -> date:
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise AdjFactorHistoryRefreshError(f"Expected YYYY-MM-DD: {value}")
    return result


def _plan(connection, lake: Path, start: str, end: str, registered: Collection[str]) -> dict:
    if _parse_day(start) > _parse_day(end) or _parse_day(end) > datetime.now(SHANGHAI).date():
        raise AdjFactorHistoryRefreshError("Invalid historical date range")
    calendar = silver_trade_calendar_path(lake)
    lifecycle = silver_stock_lifecycle_path(lake)
    calendar_identity = _identity(calendar)
    days = [row[0] for row in connection.execute(f"""
        SELECT DISTINCT CAST(CAST(trade_date AS DATE) AS VARCHAR)
        FROM {read_parquet(calendar)}
        WHERE exchange = 'SSE' AND is_open AND CAST(trade_date AS DATE) BETWEEN ? AND ?
        ORDER BY 1
        """, [_parse_day(start), _parse_day(end)]).fetchall()]
    _assert_identity(calendar, calendar_identity)
    if not days:
        raise AdjFactorHistoryRefreshError("Date range has no open SSE trading days")
    return {
        "version": 1, "lake": str(lake), "start": start, "end": end,
        "implementation": _sha256(Path(__file__)),
        "calendar": calendar_identity, "lifecycle": _identity(lifecycle), "days": days,
        "registered": [day for day in days if day in registered],
    }


def _read_day_source(day: str, pages: PageReader, cancel: Callable[[], None]) -> dict:
    iterator = iter(pages(day))
    compact_day = day.replace("-", "")
    captures, rows, keys = [], [], set()
    while True:
        cancel()
        try:
            offset, page = next(iterator)
        except StopIteration:
            raise AdjFactorHistoryRefreshError(f"Source pagination did not finish: {day}") from None
        if offset != len(captures) * PAGE_SIZE or len(page) > PAGE_SIZE:
            raise AdjFactorHistoryRefreshError(f"Invalid source page: {day}, offset {offset}")
        for row in page:
            code, factor = row.get("ts_code"), row.get("adj_factor")
            if (set(row) != set(FIELDS) or row.get("trade_date") != compact_day
                    or not isinstance(code, str) or not code or code != code.strip()
                    or code in keys or isinstance(factor, bool)
                    or not isinstance(factor, (int, float)) or not math.isfinite(factor) or factor <= 0):
                raise AdjFactorHistoryRefreshError(f"Invalid source key, date or value: {day}, {code}")
            keys.add(code)
            rows.append(row)
        captures.append({"offset": offset, "rows": len(page),
                         "received_at": datetime.now(timezone.utc).isoformat()})
        if len(page) < PAGE_SIZE:
            break
    if not rows:
        raise AdjFactorHistoryRefreshError(f"Source day is empty: {day}")
    return {"pages": captures, "rows": rows}


def _targets(lake: Path, day: str) -> dict[str, Path]:
    return {"raw": raw_adj_factor_path(lake, day), "silver": silver_adj_factor_path(lake, day)}


def _copy_query(connection, query: str, target: Path) -> None:
    _check_path(target)
    connection.execute(f"COPY ({query}) TO {duckdb_string(target)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    with target.open("rb") as stream:
        os.fsync(stream.fileno())


def _build_differences(connection, targets: dict[str, Path], lifecycle: Path) -> None:
    raw = adj_factor_normalized_select(targets["raw"])
    retained_stocks = adj_factor_retained_stock_select(lifecycle)
    silver_source = silver_adj_factor_select_from_relations("SELECT * FROM incoming", retained_stocks)
    connection.execute(f"""
        CREATE OR REPLACE TEMP TABLE differences AS
        WITH old_raw AS ({raw}), old_silver AS (SELECT * FROM {read_parquet(targets['silver'])}),
             silver_source AS ({silver_source}),
             keys AS (
                 SELECT ts_code, trade_date FROM old_raw
                 UNION SELECT ts_code, trade_date FROM old_silver
                 UNION SELECT ts_code, trade_date FROM incoming
             )
        SELECT keys.ts_code, keys.trade_date,
               r.adj_factor AS old_raw_value, s.adj_factor AS old_silver_value,
               n.adj_factor AS source_value, l.list_status, l.list_date, l.delist_date,
               CASE WHEN r.ts_code IS NULL AND n.ts_code IS NOT NULL THEN 'review'
                    WHEN r.ts_code IS NOT NULL AND n.ts_code IS NULL THEN 'retain'
                    WHEN r.ts_code IS NOT NULL AND r.adj_factor IS DISTINCT FROM n.adj_factor THEN 'update'
               END AS raw_action,
               CASE WHEN s.ts_code IS NOT NULL AND n.ts_code IS NULL THEN 'retain'
                    WHEN s.ts_code IS NOT NULL AND ss.ts_code IS NULL THEN 'lifecycle_conflict'
                    WHEN s.ts_code IS NOT NULL AND s.adj_factor IS DISTINCT FROM ss.adj_factor THEN 'update'
                    WHEN s.ts_code IS NULL AND ss.ts_code IS NOT NULL THEN
                       CASE WHEN r.ts_code IS NOT NULL AND l.list_status = 'D'
                                 AND l.list_date <= keys.trade_date AND keys.trade_date < l.delist_date
                                 AND l.delist_date < DATE {duckdb_string(ADJ_FACTOR_RETIRED_RETENTION_START_DATE)}
                            THEN 'restore' ELSE 'review' END
               END AS silver_action,
               r.ts_code IS NOT NULL AS raw_exists, s.ts_code IS NOT NULL AS silver_exists
        FROM keys
        LEFT JOIN old_raw r USING (ts_code, trade_date)
        LEFT JOIN old_silver s USING (ts_code, trade_date)
        LEFT JOIN incoming n USING (ts_code, trade_date)
        LEFT JOIN silver_source ss USING (ts_code, trade_date)
        LEFT JOIN ({retained_stocks}) l ON l.ts_code = keys.ts_code
        """)


def _actions(connection, layer: str) -> dict[str, int]:
    return dict(connection.execute(f"""
        SELECT {layer}_action, count(*) FROM differences
        WHERE {layer}_action IS NOT NULL GROUP BY 1 ORDER BY 1
        """).fetchall())


def _check_file(connection, path: Path, day: str, layer: str, lifecycle: Path, raw_path: Path) -> dict:
    return audit_adj_factor_candidate_rules(connection, path, day, raw=layer == "raw",
                                           lifecycle_path=lifecycle, raw_path=raw_path)


def _passed(counts: dict) -> bool:
    return bool(counts["rows"]) and not any(value for name, value in counts.items() if name != "rows")


def _verify_merge(connection, layer: str, old: Path, new: Path, counts: dict) -> None:
    old_sql = adj_factor_normalized_select(old) if layer == "raw" else f"SELECT * FROM {read_parquet(old)}"
    new_sql = adj_factor_normalized_select(new) if layer == "raw" else f"SELECT * FROM {read_parquet(new)}"
    action = f"d.{layer}_action"
    mismatches = connection.execute(f"""
        WITH before AS ({old_sql}), after AS ({new_sql})
        SELECT (SELECT COUNT(*) FROM (SELECT ts_code, trade_date FROM before
                         EXCEPT ALL SELECT ts_code, trade_date FROM after)),
               (SELECT COUNT(*) FROM after) - (SELECT COUNT(*) FROM before),
               (SELECT COUNT(*) FROM before b JOIN after a USING(ts_code, trade_date)
                    LEFT JOIN differences d USING(ts_code, trade_date)
                    WHERE a.adj_factor IS DISTINCT FROM
                        CASE WHEN {action} = 'update' THEN d.source_value ELSE b.adj_factor END),
               (SELECT COUNT(*) FROM after a LEFT JOIN differences d USING(ts_code, trade_date)
                    ANTI JOIN before b ON a.ts_code = b.ts_code AND a.trade_date = b.trade_date
                    WHERE {action} IS DISTINCT FROM 'restore' OR a.adj_factor IS DISTINCT FROM d.source_value)
        """).fetchone()
    if mismatches != (0, counts.get("restore", 0), 0, 0):
        raise AdjFactorHistoryRefreshError(f"Candidate differs from approved keys or values: {new}")


def _prepare_day(connection, plan: dict, run: Path, lake: Path, day: str, pages: PageReader,
                 cancel: Callable[[], None]) -> dict:
    if not adj_factor_partition_allowed_status(
        partition_key=day, registered_keys=set(plan["registered"]), today=datetime.now(SHANGHAI).date().isoformat(),
    )["passed"]:
        return {"day": day, "status": "blocked", "reason": "partition_not_allowed"}
    targets = _targets(lake, day)
    missing = [layer for layer in LAYERS if not targets[layer].is_file()]
    if missing:
        return {"day": day, "status": "blocked", "reason": "missing_old_partition", "layers": missing}
    inputs = {layer: _identity(targets[layer]) for layer in LAYERS}
    lifecycle = silver_stock_lifecycle_path(lake)
    _assert_identity(lifecycle, plan["lifecycle"])
    root = run / day
    _check_path(root)
    root.mkdir(exist_ok=True)
    attempt = Path(mkdtemp(prefix="attempt-", dir=root))
    source = _read_day_source(day, pages, cancel)
    cancel()
    source_file = attempt / "source.json"
    _checkpoint(source_file, source)
    connection.register("source_rows", pd.DataFrame(source["rows"], columns=FIELDS))
    try:
        connection.execute("""CREATE OR REPLACE TEMP TABLE incoming AS
            SELECT ts_code, strptime(trade_date, '%Y%m%d')::DATE trade_date, adj_factor::DOUBLE adj_factor
            FROM source_rows""")
    finally:
        connection.unregister("source_rows")
    _build_differences(connection, targets, lifecycle)
    diff = attempt / "differences.parquet"
    _copy_query(connection, """SELECT * EXCLUDE (raw_exists, silver_exists) FROM differences
                WHERE raw_action IS NOT NULL OR silver_action IS NOT NULL ORDER BY trade_date, ts_code""", diff)
    result = {"day": day, "status": "ready", "attempt": attempt.name, "inputs": inputs,
              "source": _fingerprint(source_file), "differences": _fingerprint(diff), "layers": {}}
    paths = targets.copy()
    for layer in LAYERS:
        actions = _actions(connection, layer)
        candidate = None
        if actions.get("update") or actions.get("restore"):
            candidate = paths[layer] = attempt / f"{layer}.parquet"
            trade_date = "strftime(trade_date, '%Y%m%d')" if layer == "raw" else "trade_date"
            _copy_query(connection, f"""
                SELECT ts_code, {trade_date} AS trade_date,
                    CASE WHEN {layer}_action IN ('update', 'restore') THEN source_value ELSE old_{layer}_value END AS adj_factor
                FROM differences WHERE {layer}_exists OR {layer}_action = 'restore' ORDER BY ts_code
                """, candidate)
        counts = _check_file(connection, paths[layer], day, layer, lifecycle, paths["raw"])
        result["layers"][layer] = {"actions": actions, "checks": counts,
                                   "candidate": _fingerprint(candidate) if candidate else None}
        if not _passed(counts):
            result["status"] = "blocked"
        _verify_merge(connection, layer, targets[layer], paths[layer], actions)
    restored_missing_raw = connection.execute(f"""
        SELECT count(*) FROM (
          SELECT ts_code, trade_date, source_value AS adj_factor FROM differences WHERE silver_action = 'restore'
          EXCEPT ALL {adj_factor_normalized_select(paths['raw'])}
        )""").fetchone()[0]
    if restored_missing_raw:
        raise AdjFactorHistoryRefreshError(f"Silver restorations do not match final Raw: {day}")
    for layer in LAYERS:
        _assert_identity(targets[layer], inputs[layer])
    _assert_identity(lifecycle, plan["lifecycle"])
    return result


def _attempt_path(run: Path, record: dict) -> Path:
    attempt = record["attempt"]
    if Path(attempt).name != attempt or not attempt.startswith("attempt-"):
        raise AdjFactorHistoryRefreshError("Invalid preparation attempt path")
    return run / record["day"] / attempt


def _verify_prepared_artifacts(run: Path, record: dict, *, include_candidates: bool) -> None:
    if "attempt" not in record:
        return
    attempt = _attempt_path(run, record)
    _assert_artifact(attempt / "source.json", record["source"])
    _assert_artifact(attempt / "differences.parquet", record["differences"])
    if include_candidates:
        for layer in LAYERS:
            candidate = record["layers"][layer]["candidate"]
            if candidate:
                _assert_artifact(attempt / f"{layer}.parquet", candidate)


def prepare_history_refresh(*, lake: Path, staging: Path, operation_id: str, start: str, end: str,
                            registered: Collection[str], pages: PageReader,
                            cancel: Callable[[], None] = _noop,
                            progress: Callable[[dict], None] = _no_progress) -> dict:
    """Freeze the dated inputs and write candidates only under this staging execution."""
    with _operation(lake, staging, operation_id) as run:
        run.mkdir(exist_ok=True)
        plan_file, seal = run / "plan.json", run / "sealed.json"
        with _connect(run) as connection:
            plan = _plan(connection, lake, start, end, registered)
            if plan_file.exists():
                if _json(plan_file) != plan:
                    raise AdjFactorHistoryRefreshError("Preparation scope or inputs changed")
            else:
                _checkpoint(plan_file, plan)
            if seal.exists():
                sealed = _json(seal)
                if sealed["plan_sha256"] != _sha256(plan_file):
                    raise AdjFactorHistoryRefreshError("Sealed plan changed")
                return sealed
            receipts = {}
            for index, day in enumerate(plan["days"], 1):
                cancel()
                checkpoint = run / f"{day}.json"
                if checkpoint.exists():
                    record = _json(checkpoint)
                    _verify_prepared_artifacts(run, record, include_candidates=True)
                    for layer, identity in record.get("inputs", {}).items():
                        _assert_identity(_targets(lake, day)[layer], identity)
                else:
                    record = _prepare_day(connection, plan, run, lake, day, pages, cancel)
                    _checkpoint(checkpoint, record)
                receipts[day] = {"sha256": _sha256(checkpoint), "status": record["status"]}
                progress({"phase": "prepare", "day": day, "completed": index, "total": len(plan["days"]),
                          "status": record["status"]})
            _assert_identity(silver_trade_calendar_path(lake), plan["calendar"])
            _assert_identity(silver_stock_lifecycle_path(lake), plan["lifecycle"])
            sealed = {"plan_sha256": _sha256(plan_file), "days": receipts}
            _checkpoint(seal, sealed)
        return sealed


def _load_sealed(run: Path, lake: Path) -> tuple[dict, dict]:
    plan_file = run / "plan.json"
    plan, sealed = _json(plan_file), _json(run / "sealed.json")
    if (plan["lake"] != str(lake) or plan["implementation"] != _sha256(Path(__file__))
            or sealed["plan_sha256"] != _sha256(plan_file)
            or plan["days"] != sorted(sealed["days"])):
        raise AdjFactorHistoryRefreshError("Sealed execution does not match its plan or target")
    _assert_identity(silver_trade_calendar_path(lake), plan["calendar"])
    _assert_identity(silver_stock_lifecycle_path(lake), plan["lifecycle"])
    return plan, sealed


def _sealed_day(run: Path, day: str, entry: dict) -> dict:
    _parse_day(day)
    path = run / f"{day}.json"
    if _sha256(path) != entry["sha256"]:
        raise AdjFactorHistoryRefreshError(f"Preparation checkpoint changed: {day}")
    record = _json(path)
    if record["day"] != day or record["status"] != entry["status"]:
        raise AdjFactorHistoryRefreshError(f"Unexpected preparation checkpoint: {day}")
    return record


def _publish_state(run: Path, day: str, layer: str, target: Path, prior: dict,
                   candidate: Path, sealed: dict | None) -> tuple[Path, dict | None]:
    control = run / day / f"{layer}-publication.json"
    state = _json(control) if control.exists() else None
    if state is not None:
        if state["phase"] not in {"prepared", "verified"} or state["candidate"] != sealed:
            raise AdjFactorHistoryRefreshError(f"Publication receipt conflicts with seal: {control}")
        if state["phase"] == "verified":
            _assert_identity(target, state["target"])
            return control, state
    if sealed and state and not candidate.exists():
        _assert_artifact(target, sealed, moved=True)
    else:
        _assert_identity(target, prior)
        if sealed:
            _assert_artifact(candidate, sealed)
    return control, state


def _publish_layer(connection, day: str, layer: str, target: Path, candidate: Path,
                   sealed: dict | None, control: Path, state: dict | None,
                   raw_path: Path, lifecycle: Path, expected_checks: dict) -> dict:
    if state and state["phase"] == "verified":
        return state
    if sealed:
        if state is None:
            _checkpoint(control, {"phase": "prepared", "candidate": sealed})
        if candidate.exists():
            os.replace(candidate, target)
            descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        _assert_artifact(target, sealed, moved=True)
    identity = _identity(target)
    checks = _check_file(connection, target, day, layer, lifecycle, raw_path)
    if not _passed(checks) or checks != expected_checks:
        raise AdjFactorHistoryRefreshError(f"Published file failed readback: {target}")
    _assert_identity(target, identity)
    state = {"phase": "verified", "candidate": sealed, "target": identity, "checks": checks,
             "changed": sealed is not None}
    _checkpoint(control, state)
    return state


def publish_history_refresh(*, lake: Path, staging: Path, operation_id: str,
                            registered: Collection[str], cancel: Callable[[], None] = _noop,
                            progress: Callable[[dict], None] = _no_progress) -> dict:
    """Promote sealed candidates and finalize each date after physical readback."""
    with _operation(lake, staging, operation_id) as run:
        plan, sealed = _load_sealed(run, lake)
        totals = {"days": 0, "blocked": 0, "raw_changed": 0, "silver_changed": 0}
        lifecycle = silver_stock_lifecycle_path(lake)
        with _connect(run) as connection:
            for index, day in enumerate(plan["days"], 1):
                cancel()
                record = _sealed_day(run, day, sealed["days"][day])
                if record["status"] != "ready":
                    totals["blocked"] += 1
                    continue
                if day not in registered:
                    raise AdjFactorHistoryRefreshError(f"Partition no longer registered: {day}")
                _assert_identity(lifecycle, plan["lifecycle"])
                _verify_prepared_artifacts(run, record, include_candidates=False)
                attempt, targets = _attempt_path(run, record), _targets(lake, day)
                states = {}
                for layer in LAYERS:
                    states[layer] = _publish_state(run, day, layer, targets[layer], record["inputs"][layer],
                                                   attempt / f"{layer}.parquet", record["layers"][layer]["candidate"])
                for layer in LAYERS:
                    cancel()
                    candidate = attempt / f"{layer}.parquet"
                    sealed_file = record["layers"][layer]["candidate"]
                    control, state = states[layer]
                    if state is None or (state["phase"] == "prepared" and candidate.exists()):
                        _assert_identity(targets[layer], record["inputs"][layer])
                        if sealed_file:
                            _assert_identity(candidate, sealed_file["identity"])
                    result = _publish_layer(connection, day, layer, targets[layer], candidate, sealed_file,
                                            control, state, targets["raw"], lifecycle,
                                            record["layers"][layer]["checks"])
                    totals[f"{layer}_changed"] += result["changed"]
                _assert_identity(lifecycle, plan["lifecycle"])
                totals["days"] += 1
                progress({"phase": "publish", "day": day, "completed": index, "total": len(plan["days"]), **totals})
        _checkpoint(run / "published.json", totals)
        return totals
