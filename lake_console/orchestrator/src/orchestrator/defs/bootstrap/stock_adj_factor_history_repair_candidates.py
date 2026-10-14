"""Columnar scoped candidates, audited before any formal file promotion."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path

from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
    RepairBudget,
    atomic_repair_json,
    check_repair_cancel,
    check_repair_path,
    file_identity,
    repair_hash,
    repair_price_dates,
    sync_repair_directory,
    validate_price_repair_units,
    write_candidate_record,
)
from orchestrator.defs.duckdb_sql import read_parquet


def _relation(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise FactorRepairError("repair_relation_invalid")
    return '"' + name + '"'


def _columns(schema) -> str:
    return ", ".join('"' + column.name + '"' for column in schema)


def _scalar(connection, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def assert_repair_schema(connection, path: Path, schema) -> None:
    expected = [(column.name, column.type) for column in schema]
    observed = [(row[0], row[1]) for row in connection.execute(
        f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
    ).fetchall()]
    if observed != expected:
        raise FactorRepairError("repair_schema_mismatch")


def build_scoped_file_candidate(
    connection, *, lake_root: Path, run_root: Path, target: Path,
    replacement_relation: str, approved_keys_relation: str, schema,
    key_columns: tuple[str, ...], plan_hash: str, unit_id: str,
    asset_key: str, partition_key: str, validator, finalize_record, cancel=None,
) -> dict:
    """Replace existing approved keys exactly; unchanged business rows create no file.

    The caller supplies the asset's shared pure validator. This function performs
    transfer/scope integrity, not a second implementation of business checks.
    """
    check_repair_cancel(cancel)
    check_repair_path(target)
    check_repair_path(run_root)
    if not target.is_relative_to(lake_root) or target.suffix != ".parquet":
        raise FactorRepairError("repair_target_path_invalid")
    relative = target.relative_to(lake_root).as_posix()
    if relative.split("/")[0] not in ("raw", "silver", "gold"):
        raise FactorRepairError("repair_target_path_invalid")
    replacement = _relation(replacement_relation)
    allowed = _relation(approved_keys_relation)
    if not key_columns or set(key_columns) - {column.name for column in schema}:
        raise FactorRepairError("repair_key_contract_invalid")
    keys = ", ".join('"' + column + '"' for column in key_columns)
    columns = _columns(schema)
    before = file_identity(target, cancel=cancel)
    assert_repair_schema(connection, target, schema)
    connection.execute(f"CREATE OR REPLACE TEMP VIEW repair_original AS SELECT {columns} FROM {read_parquet(target, hive_partitioning=False)}")
    for relation in ("repair_original", replacement, allowed):
        if _scalar(connection, f"SELECT count(*) FROM (SELECT {keys} FROM {relation} GROUP BY {keys} HAVING count(*)<>1)"):
            raise FactorRepairError("repair_duplicate_keys")
        nulls = " OR ".join('"' + key + '" IS NULL' for key in key_columns)
        if _scalar(connection, f"SELECT count(*) FROM {relation} WHERE {nulls}"):
            raise FactorRepairError("repair_null_key")
    for query in (
        f"SELECT {keys} FROM {replacement} EXCEPT SELECT {keys} FROM {allowed}",
        f"SELECT {keys} FROM {replacement} EXCEPT SELECT {keys} FROM repair_original",
        f"SELECT {keys} FROM {allowed} EXCEPT SELECT {keys} FROM {replacement}",
    ):
        if _scalar(connection, f"SELECT count(*) FROM ({query})"):
            raise FactorRepairError("repair_replacement_keys_invalid")
    replacement_rows = _scalar(connection, f"SELECT count(*) FROM {replacement}")
    changed_rows = _scalar(connection, f"SELECT count(*) FROM (SELECT {columns} FROM {replacement} EXCEPT ALL SELECT {columns} FROM repair_original)")
    original_rows = _scalar(connection, "SELECT count(*) FROM repair_original")
    common = {"plan_hash": plan_hash, "unit_id": unit_id, "asset_key": asset_key,
              "partition_key": partition_key, "target_relative_path": relative,
              "preimage_sha256": before.sha256, "original_rows": original_rows,
              "replacement_rows": replacement_rows, "changed_stock_rows": changed_rows}
    if not changed_rows:
        validator(connection, target, partition_key)
        record = {**common, "no_op": True, "candidate_relative_path": None,
                  "candidate_sha256": before.sha256, "candidate_rows": original_rows,
                  "candidate_bytes": 0, "validated": True}
        if file_identity(target, cancel=cancel) != before:
            raise FactorRepairError("target_drift")
        finalize_record(record)
        return record
    candidate = run_root / "candidates" / relative
    check_repair_path(candidate)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    proof_path = repair_record_path(run_root,target,lake_root)
    working = candidate.with_suffix(candidate.suffix + ".partial")
    if candidate.exists() or working.exists():
        if not proof_path.exists():
            raise FactorRepairError("repair_unowned_candidate")
        proof = json.loads(check_repair_path(proof_path).read_text())
        if (proof.get("plan_hash") != plan_hash or proof.get("preimage_sha256") != before.sha256
            or proof.get("target_relative_path") != relative or proof.get("asset_key") != asset_key
            or proof.get("unit_id") != unit_id
            or proof.get("candidate_relative_path") != candidate.relative_to(run_root).as_posix()
            or proof.get("validated") is not False
            or "record_hash" in proof):
            raise FactorRepairError("repair_unowned_candidate")
        for unfinished in (candidate,working):
            check_repair_path(unfinished)
            if unfinished.exists():
                unfinished.unlink()
    write_candidate_record(run_root,{**common,"validated":False,
        "candidate_relative_path":candidate.relative_to(run_root).as_posix()})
    join = " AND ".join(f'o."{key}" IS NOT DISTINCT FROM k."{key}"' for key in key_columns)
    merged = f"""
    SELECT {columns} FROM repair_original o
    WHERE NOT EXISTS (SELECT 1 FROM {allowed} k WHERE {join})
    UNION ALL
    SELECT {columns} FROM {replacement}
    """
    check_repair_cancel(cancel)
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
        bounded_repair_copy,
    )
    bounded_repair_copy(connection, f"SELECT {columns} FROM ({merged}) ORDER BY {keys}",
                        run_root,working,candidate=True,reserve_bytes=before.size)
    candidate_output = candidate
    candidate = working
    with candidate.open("rb") as stream:
        os.fsync(stream.fileno())
    sync_repair_directory(candidate.parent)
    check_repair_cancel(cancel)
    assert_repair_schema(connection, candidate, schema)
    validator(connection, candidate, partition_key)
    connection.execute(f"CREATE OR REPLACE TEMP VIEW repair_candidate AS SELECT {columns} FROM {read_parquet(candidate, hive_partitioning=False)}")
    candidate_rows = _scalar(connection, "SELECT count(*) FROM repair_candidate")
    if candidate_rows != original_rows:
        raise FactorRepairError("repair_row_count_changed")
    if _scalar(connection, f"SELECT count(*) FROM (SELECT {keys} FROM repair_candidate GROUP BY {keys} HAVING count(*)<>1)"):
        raise FactorRepairError("repair_duplicate_keys")
    for side, other in (("repair_candidate", "repair_original"), ("repair_original", "repair_candidate")):
        retained = lambda relation: f"SELECT {columns} FROM {relation} o WHERE NOT EXISTS (SELECT 1 FROM {allowed} k WHERE {join})"
        if _scalar(connection, f"SELECT count(*) FROM ({retained(side)} EXCEPT ALL {retained(other)})"):
            raise FactorRepairError("repair_retained_rows_changed")
    for left, right in (("repair_candidate", replacement), (replacement, "repair_candidate")):
        approved_rows = f"SELECT {columns} FROM {left} o WHERE EXISTS (SELECT 1 FROM {allowed} k WHERE {join})"
        if _scalar(connection, f"SELECT count(*) FROM ({approved_rows} EXCEPT ALL SELECT {columns} FROM {right} o WHERE EXISTS (SELECT 1 FROM {allowed} k WHERE {join}))"):
            raise FactorRepairError("repair_candidate_value_mismatch")
    if file_identity(target, cancel=cancel) != before:
        raise FactorRepairError("target_drift")
    candidate_identity = file_identity(candidate, cancel=cancel)
    record = {**common, "no_op": False,
              "candidate_relative_path": candidate.relative_to(run_root).as_posix(),
              "candidate_sha256": candidate_identity.sha256,
              "candidate_rows": candidate_rows, "candidate_bytes": candidate_identity.size,
              "validated": True}
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
        check_repair_storage,
    )
    check_repair_storage(run_root)
    os.replace(candidate,candidate_output)
    sync_repair_directory(candidate_output.parent)
    record["candidate_relative_path"] = candidate_output.relative_to(run_root).as_posix()
    finalize_record(record)
    return record


PRICE_REPAIR_ASSETS = (
    "raw_tushare_adj_factor", "silver_adj_factor", "gold_stock_daily_qfq",
    *(f"gold_stk_mins_qfq_{freq}m" for freq in (1, 5, 15, 30, 60, 90, 120)),
)


def repair_record_path(run_root: Path, target: Path, lake_root: Path) -> Path:
    relative = target.relative_to(lake_root).as_posix()
    import hashlib
    return run_root / "checkpoints/candidates" / (hashlib.sha256(relative.encode()).hexdigest() + ".json")


class RepairCandidateInputs:
    """One frozen input or one validated overlay; projections contain all approved stocks."""

    def __init__(self, connection, plan, cancel=None):
        self.connection, self.plan, self.cancel = connection, plan, cancel
        self.lake_root, self.run_root = Path(plan["lake_root"]), Path(plan["run_root"])
        self.identities = {i["path"]: i for i in plan["source_fingerprints"]}
        self.verified = set()
        self.require_factor_candidates = False
        self.overlays = {}
        self.codes = ",".join("'" + s["ts_code"] + "'" for s in plan["scopes"])

    def frozen(self, path: Path) -> Path:
        path = check_repair_path(path)
        identity = self.identities.get(str(path))
        if identity is None:
            raise FactorRepairError("repair_input_not_frozen")
        if str(path) not in self.verified:
            if asdict(file_identity(path, cancel=self.cancel)) != identity:
                raise FactorRepairError("input_drift")
            self.verified.add(str(path))
        return path

    def resolve(self, path: Path) -> Path:
        self.frozen(path)
        record_path = repair_record_path(self.run_root, path, self.lake_root)
        if not record_path.exists():
            if self.require_factor_candidates and "/adj_factor/" in path.as_posix():
                day = path.parent.name.removeprefix("trade_date=").replace("-", "")
                if any(r["trade_date"] == day for r in self.plan["source_rows"]):
                    raise FactorRepairError("repair_factor_candidate_required")
            return path
        record = read_repair_candidate_record(self.plan, path)
        self.overlays[str(path)] = record["candidate_sha256"]
        return path if record["no_op"] else self.run_root / record["candidate_relative_path"]

    def project(self, path: Path) -> Path:
        """SQL projection once per shared input; identity binds it to this frozen version."""
        source = self.resolve(path)
        relative = path.relative_to(self.lake_root)
        output = self.run_root / "inputs" / relative
        receipt = output.with_suffix(".json")
        identity = asdict(file_identity(source, cancel=self.cancel))
        if source == path and identity != self.identities[str(path)]:
            raise FactorRepairError("input_drift")
        if source != path:
            record = read_repair_candidate_record(self.plan, path)
            if identity["sha256"] != record["candidate_sha256"]:
                raise FactorRepairError("repair_candidate_drift")
        output = check_repair_path(output)
        working = check_repair_path(output.with_suffix(output.suffix + ".partial"))
        if receipt.exists():
            proof = json.loads(check_repair_path(receipt).read_text())
            if (proof.get("plan_hash") != self.plan["plan_hash"] or proof.get("source") != identity
                or proof.get("output_path") != str(output)):
                raise FactorRepairError("repair_projection_drift")
            if proof.get("validated") is True:
                if proof.get("output") != asdict(file_identity(output,cancel=self.cancel)) or working.exists():
                    raise FactorRepairError("repair_projection_drift")
                return output
            if proof.get("validated") is not False:
                raise FactorRepairError("repair_projection_drift")
            for unfinished in (output,working):
                if unfinished.exists():
                    unfinished.unlink()
        elif output.exists() or working.exists():
            raise FactorRepairError("repair_projection_unowned")
        output.parent.mkdir(parents=True,exist_ok=True)
        ownership = {"plan_hash":self.plan["plan_hash"],"source":identity,"output_path":str(output)}
        atomic_repair_json(receipt,{**ownership,"validated":False})
        columns = [str(r[0]) for r in self.connection.execute(
            f"DESCRIBE SELECT * FROM {read_parquet(source, hive_partitioning=False)}").fetchall()]
        if "ts_code" not in columns:
            raise FactorRepairError("repair_projection_contract_invalid")
        selected = ",".join('"' + column + '"' for column in columns)
        check_repair_cancel(self.cancel)
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
            bounded_repair_copy,
        )
        bounded_repair_copy(self.connection,
            f"SELECT {selected} FROM {read_parquet(source, hive_partitioning=False)} WHERE ts_code IN ({self.codes})",
            self.run_root,working,reserve_bytes=identity["size"])
        with working.open("rb") as stream:
            os.fsync(stream.fileno())
        sync_repair_directory(output.parent)
        check_repair_cancel(self.cancel)
        if asdict(file_identity(source,cancel=self.cancel)) != identity:
            raise FactorRepairError("input_drift")
        os.replace(working,output)
        sync_repair_directory(output.parent)
        atomic_repair_json(receipt,{**ownership,"validated":True,
            "output":asdict(file_identity(output,cancel=self.cancel))})
        return output


def read_repair_candidate_record(plan, target: Path) -> dict:
    root, run = Path(plan["lake_root"]), Path(plan["run_root"])
    record = json.loads(check_repair_path(repair_record_path(run, target, root)).read_text())
    relative = target.relative_to(root).as_posix()
    preimage = next((i for i in plan["target_preimages"] if i["path"] == str(target)), None)
    owner = next((u["asset_key"] for u in plan["units"] if str(target) in u["target_paths"]),None)
    if (record.get("asset_key") != owner or record.get("unit_id") != repair_hash([plan["plan_hash"],owner,str(target)])
        or any(type(record.get(k)) is not int or record[k] < 0 for k in ("original_rows","replacement_rows","changed_stock_rows","candidate_rows","candidate_bytes"))
        or record.get("candidate_rows") != record.get("original_rows")
        or record.get("changed_stock_rows",0) > record.get("replacement_rows",0)
        or type(record.get("no_op")) is not bool
        or record["no_op"] != (record.get("changed_stock_rows") == 0)):
        raise FactorRepairError("repair_candidate_record_invalid")
    if (preimage is None or record.get("plan_hash") != plan["plan_hash"]
            or record.get("target_relative_path") != relative
            or record.get("preimage_sha256") != preimage["sha256"]
            or record.get("validated") is not True or record.get("record_hash") != repair_hash(
                {k: v for k, v in record.items() if k != "record_hash"})):
        raise FactorRepairError("repair_candidate_record_invalid")
    if asdict(file_identity(target)) != preimage:
        raise FactorRepairError("target_drift")
    if record["no_op"]:
        if record.get("candidate_relative_path") is not None or record["candidate_sha256"] != preimage["sha256"] or record["candidate_bytes"] != 0:
            raise FactorRepairError("repair_candidate_record_invalid")
    else:
        expected = "candidates/" + relative
        if record.get("candidate_relative_path") != expected:
            raise FactorRepairError("repair_candidate_path_invalid")
        output = file_identity(check_repair_path(run / expected))
        if output.sha256 != record["candidate_sha256"] or output.size != record["candidate_bytes"]:
            raise FactorRepairError("repair_candidate_drift")
    return record


def repair_target_scope(plan, unit, target: Path) -> dict:
    """Recheck frozen price dates against exact source keys; never infer a wider repair."""
    from orchestrator.defs import paths
    validate_price_repair_units(plan)
    asset = unit["asset_key"]
    if asset not in PRICE_REPAIR_ASSETS or str(target) not in unit["target_paths"]:
        raise FactorRepairError("repair_phase_not_supported")
    relative = target.relative_to(Path(plan["lake_root"])).as_posix()
    if asset in PRICE_REPAIR_ASSETS[:2]:
        day = target.parent.name.removeprefix("trade_date=")
        rows = [r for r in plan["source_rows"] if r["trade_date"] == day.replace("-", "")]
        if not rows:
            raise FactorRepairError("repair_factor_target_not_approved")
        return {"day": day, "rows": rows, "codes": [r["ts_code"] for r in rows], "freq": None}
    profiles = unit.get("calculation_windows", ())
    selected = []
    freq = None if asset == "gold_stock_daily_qfq" else int(asset.rsplit("_", 1)[1][:-1])
    for profile in profiles:
        code = profile["ts_code"]
        if code not in {s["ts_code"] for s in plan["scopes"]} or profile["freq"] != freq:
            raise FactorRepairError("repair_price_scope_invalid")
        scope = next(s for s in plan["scopes"] if s["ts_code"] == code)
        observed = tuple(profile["observed_dates"])
        if not observed or (profile.get("previous_actual_date") and profile["previous_actual_date"] >= observed[0]):
            raise FactorRepairError("repair_previous_source_date_invalid")
        allowed = set(repair_price_dates(plan,profile,daily=freq is None))
        order = profile["source_dates"] if freq is None else observed
        previous = {day: before for before, day in pairwise(order)}
        if freq is not None and profile.get("previous_actual_date"):
            previous[observed[0]] = profile["previous_actual_date"]
        if (set(profile["target_dates"]) != allowed or observed != tuple(sorted(set(observed)))
                or profile["end_time"][:10] != observed[-1]
                or profile["end_time"][:10] > scope["repair_end_trade_date"]):
            raise FactorRepairError("repair_price_dates_not_approved")
        if not allowed <= {d for window in profile["windows"] for d in window}:
            raise FactorRepairError("repair_price_windows_incomplete")
        dates = [d for d in sorted(allowed) if str(
            paths.gold_stock_daily_qfq_path(Path(plan["lake_root"]), d) if freq is None else
            paths.gold_stk_mins_qfq_path(Path(plan["lake_root"]), freq, code, d[:4])) == str(target)]
        if dates:
            selected.append({"code": code, "dates": dates, "previous": previous,
                             "as_of": scope["as_of_trade_date"], "windows": profile["windows"],
                             "source_dates": profile.get("source_dates"),
                             "source_inventory_paths": profile.get("source_inventory_paths")})
    if not selected:
        raise FactorRepairError("repair_price_target_not_approved")
    return {"day": target.parent.name.removeprefix("trade_date=") if freq is None else None,
            "profiles": selected, "codes": [p["code"] for p in selected], "freq": freq,
            "relative": relative}


def prepare_repair_replacement(connection, plan, unit, target: Path, *, cancel=None):
    """Canonical SQL only. Business rows stay in DuckDB and bounded staging fragments."""
    from orchestrator.defs import paths
    from orchestrator.defs.duckdb_sql import duckdb_string, silver_adj_factor_select
    from orchestrator.defs.run_contracts.asset_column_schemas import (
        GOLD_STK_MINS_QFQ_SCHEMA,
        GOLD_STOCK_DAILY_QFQ_SCHEMA,
        RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
        SILVER_ADJ_FACTOR_SCHEMA,
    )
    from orchestrator.defs.stk_mins_qfq import (
        build_canonical_gold_stk_mins_qfq_diagnostics_sql,
        build_canonical_gold_stk_mins_qfq_select_sql,
        gold_stk_mins_qfq_source_freq,
    )
    from orchestrator.defs.stock_daily_qfq import build_stock_daily_qfq_select_sql
    asset, root = unit["asset_key"], Path(plan["lake_root"])
    selected = repair_target_scope(plan, unit, target)
    inputs = RepairCandidateInputs(connection, plan, cancel)
    inputs.require_factor_candidates = asset not in PRICE_REPAIR_ASSETS[:2]
    inputs.frozen(target)
    codes_sql = ",".join(duckdb_string(c) for c in selected["codes"])
    if asset == "raw_tushare_adj_factor":
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
            create_factor_source_relation,
        )
        create_factor_source_relation(connection, selected["rows"])
        query = "SELECT ts_code,trade_date,CAST(adj_factor AS DOUBLE) AS adj_factor FROM repair_source"
        schema = RAW_TUSHARE_ADJ_FACTOR_SCHEMA
    elif asset == "silver_adj_factor":
        raw_target = paths.raw_adj_factor_path(root, selected["day"])
        if not repair_record_path(Path(plan["run_root"]), raw_target, root).exists():
            raise FactorRepairError("repair_factor_candidate_required")
        query = f"SELECT * FROM ({silver_adj_factor_select(inputs.resolve(raw_target), inputs.frozen(paths.silver_stock_lifecycle_path(root)))}) WHERE ts_code IN ({codes_sql})"
        schema = SILVER_ADJ_FACTOR_SCHEMA
    else:
        schema = GOLD_STOCK_DAILY_QFQ_SCHEMA if selected["freq"] is None else GOLD_STK_MINS_QFQ_SCHEMA
        connection.execute("CREATE OR REPLACE TEMP TABLE repair_replacement(" +
            ",".join('"' + c.name + '" ' + c.type for c in schema) + ")")
        for profile in selected["profiles"]:
            check_repair_cancel(cancel)
            code, as_of = profile["code"], profile["as_of"]
            anchor = inputs.project(paths.silver_adj_factor_path(root, as_of))
            expected_anchor = next(a for a in plan["anchors"] if a["ts_code"] == code)
            anchor_rows = connection.execute(f"SELECT adj_factor FROM {read_parquet(anchor, hive_partitioning=False)} WHERE ts_code=? AND trade_date=CAST(? AS DATE)", [code, as_of]).fetchall()
            if len(anchor_rows) != 1 or anchor_rows[0][0] != float(expected_anchor["adj_factor"]):
                raise FactorRepairError("repair_anchor_drift")
            if selected["freq"] is None:
                day = selected["day"]
                inventory_key = repair_hash([plan["plan_hash"],profile["source_inventory_paths"]])
                exists = connection.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name='repair_daily_source_inventory'").fetchone()[0]
                if not exists:
                    connection.execute("CREATE TEMP TABLE repair_daily_source_inventory(ts_code VARCHAR,trade_date DATE)")
                    for offset in range(0,len(profile["source_inventory_paths"]),64):
                        batch = [inputs.project(Path(p)) for p in profile["source_inventory_paths"][offset:offset+64]]
                        source_sql = "read_parquet([" + ",".join(duckdb_string(p) for p in batch) + "],hive_partitioning=false)"
                        connection.execute(f"INSERT INTO repair_daily_source_inventory SELECT ts_code,trade_date FROM {source_sql}")
                    connection.execute("CREATE TEMP TABLE repair_daily_inventory_binding AS SELECT ?::VARCHAR binding",[inventory_key])
                if connection.execute("SELECT binding FROM repair_daily_inventory_binding").fetchone()[0] != inventory_key:
                    raise FactorRepairError("repair_daily_source_inventory_drift")
                # Cached business index is bounded by 25 stocks x actual daily dates.
                # Each target still binds every inventory source fingerprint independently.
                for name in profile["source_inventory_paths"]:
                    inputs.frozen(Path(name))
                rows = connection.execute("SELECT CAST(trade_date AS VARCHAR),count(*) FROM repair_daily_source_inventory WHERE ts_code=? AND trade_date<=CAST(? AS DATE) GROUP BY trade_date ORDER BY trade_date",[code,profile["source_dates"][-1]]).fetchall()
                if any(n != 1 for d,n in rows):
                    raise FactorRepairError("repair_daily_source_duplicate_key")
                if [d for d,n in rows] != list(profile["source_dates"]):
                    raise FactorRepairError("repair_daily_source_inventory_drift")
                previous = profile["previous"].get(day)
                previous_daily = [] if previous is None else [inputs.project(paths.silver_stock_daily_path(root, previous))]
                if previous is not None and _scalar(connection, f"SELECT count(*) FROM {read_parquet(previous_daily[0], hive_partitioning=False)} WHERE ts_code={duckdb_string(code)} AND trade_date=DATE {duckdb_string(previous)}") != 1:
                    raise FactorRepairError("repair_previous_source_row_missing")
                if previous is None:
                    lifecycle = inputs.frozen(paths.silver_stock_lifecycle_path(root))
                    if _scalar(connection, f"SELECT count(*) FROM {read_parquet(lifecycle, hive_partitioning=False)} WHERE ts_code={duckdb_string(code)} AND list_date=DATE {duckdb_string(day)}") != 1:
                        raise FactorRepairError("repair_daily_initialization_not_approved")
                query = build_stock_daily_qfq_select_sql(
                    stock_daily_path=inputs.project(paths.silver_stock_daily_path(root, day)),
                    trade_adj_factor_path=inputs.project(paths.silver_adj_factor_path(root, day)),
                    previous_stock_daily_paths=previous_daily,
                    previous_adj_factor_paths=[] if previous is None else [inputs.project(paths.silver_adj_factor_path(root, previous))],
                    as_of_adj_factor_path=anchor, trade_date=day, as_of_trade_date=as_of)
                connection.execute(f"INSERT INTO repair_replacement SELECT * FROM ({query}) WHERE ts_code={duckdb_string(code)}")
            else:
                freq = selected["freq"]
                for window in profile["windows"]:
                    dates = [d for d in window if d in profile["dates"]]
                    if not dates:
                        continue
                    silver = [inputs.project(paths.silver_stk_mins_path(root, gold_stk_mins_qfq_source_freq(freq), d)) for d in dates]
                    factors = [inputs.project(paths.silver_adj_factor_path(root, d)) for d in dates]
                    diagnostics = connection.execute(build_canonical_gold_stk_mins_qfq_diagnostics_sql(
                        silver_paths=silver, target_freq=freq, partition_keys=dates, stock_codes=[code])).fetchone()
                    if diagnostics[3] <= 0 or diagnostics[4] != diagnostics[5] or diagnostics[6] or diagnostics[7]:
                        raise FactorRepairError("repair_minute_source_incomplete")
                    query = build_canonical_gold_stk_mins_qfq_select_sql(
                        silver_paths=silver, trade_adj_factor_paths=factors,
                        as_of_adj_factor_paths=[anchor], target_freq=freq,
                        partition_keys=dates, stock_codes=[code])
                    connection.execute(f"CREATE OR REPLACE TEMP TABLE repair_fragment AS {query}")
                    if _scalar(connection, "SELECT count(*) FROM repair_fragment") > RepairBudget().max_stock_batch_rows:
                        raise FactorRepairError("repair_stock_row_budget_exceeded")
                    connection.execute("INSERT INTO repair_replacement SELECT * FROM repair_fragment")
                    check_repair_cancel(cancel)
        query = "SELECT * FROM repair_replacement"
    if asset in PRICE_REPAIR_ASSETS[:2]:
        connection.execute(f"CREATE OR REPLACE TEMP TABLE repair_replacement AS {query}")
    keys = ("ts_code", "trade_date") if selected["freq"] is None else ("ts_code", "trade_time")
    if asset in PRICE_REPAIR_ASSETS[:2]:
        day = selected["day"] if asset == "silver_adj_factor" else selected["day"].replace("-", "")
        where = f"ts_code IN ({codes_sql}) AND trade_date={duckdb_string(day)}"
    elif selected["freq"] is None:
        where = f"ts_code IN ({codes_sql}) AND trade_date=DATE {duckdb_string(selected['day'])}"
    else:
        where = " OR ".join(f"(ts_code={duckdb_string(p['code'])} AND trade_date IN (" +
            ",".join("DATE " + duckdb_string(d) for d in p["dates"]) + "))" for p in selected["profiles"])
    connection.execute(f"CREATE OR REPLACE TEMP TABLE repair_approved AS SELECT {','.join(keys)} FROM {read_parquet(target, hive_partitioning=False)} WHERE {where}")
    if asset not in PRICE_REPAIR_ASSETS[:2]:
        for left, right in (("repair_replacement", "repair_approved"), ("repair_approved", "repair_replacement")):
            if _scalar(connection, f"SELECT count(*) FROM (SELECT {','.join(keys)} FROM {left} EXCEPT SELECT {','.join(keys)} FROM {right})"):
                raise FactorRepairError("repair_replacement_keys_invalid")
        # Preserve existing quantity fields exactly; the one-off diagnostic keeps source noise visible.
        join = " AND ".join(f'r."{k}" IS NOT DISTINCT FROM o."{k}"' for k in keys)
        from orchestrator.defs.bootstrap.stk_mins_qfq_derived_history import (
            GOLD_STK_MINS_QFQ_DERIVED_AMOUNT_ABS_TOLERANCE,
        )
        if selected["freq"] is not None and _scalar(connection,f"SELECT count(*) FROM repair_replacement r JOIN {read_parquet(target,hive_partitioning=False)} o ON {join} WHERE r.freq IS DISTINCT FROM o.freq OR r.trade_date IS DISTINCT FROM o.trade_date OR r.exchange IS DISTINCT FROM o.exchange"):
            raise FactorRepairError("repair_minute_identity_changed")
        amount_tolerance = 0 if selected["freq"] is None else GOLD_STK_MINS_QFQ_DERIVED_AMOUNT_ABS_TOLERANCE
        if _scalar(connection, f"SELECT count(*) FROM repair_replacement r JOIN {read_parquet(target, hive_partitioning=False)} o ON {join} WHERE r.vol IS DISTINCT FROM o.vol OR r.amount IS NULL OR o.amount IS NULL OR abs(r.amount-o.amount)>{amount_tolerance}"):
            raise FactorRepairError("repair_quantity_changed")
        selected["max_source_amount_abs_difference"] = float(connection.execute(
            f"SELECT coalesce(max(abs(r.amount-o.amount)),0) FROM repair_replacement r JOIN {read_parquet(target, hive_partitioning=False)} o ON {join}").fetchone()[0])
        columns = ",".join(f'o."{c.name}"' if c.name in ("vol", "amount") else f'r."{c.name}"' for c in schema)
        connection.execute(f"CREATE OR REPLACE TEMP TABLE repair_quantity_preserved AS SELECT {columns} FROM repair_replacement r JOIN {read_parquet(target, hive_partitioning=False)} o ON {join}")
        connection.execute("CREATE OR REPLACE TEMP TABLE repair_replacement AS SELECT * FROM repair_quantity_preserved")
    return schema, keys, selected, inputs


def validate_repair_business_file(connection, plan, target, output, selected, inputs, schema):
    """Same pure production rules plus the transfer integrity of this approved scope."""
    from orchestrator.defs import paths
    from orchestrator.defs.stock_factor_price_checks import (
        audit_adj_factor_candidate_rules,
        daily_qfq_contract_rule_counts,
        minute_qfq_counts_sql,
        minute_qfq_identity_coverage_counts_sql,
    )
    assert_repair_schema(connection, output, schema)
    asset = next(u["asset_key"] for u in plan["units"] if str(target) in u["target_paths"])
    if asset in PRICE_REPAIR_ASSETS[:2]:
        counts = audit_adj_factor_candidate_rules(connection, output, selected["day"],
            raw=asset == "raw_tushare_adj_factor", lifecycle_path=inputs.frozen(paths.silver_stock_lifecycle_path(Path(plan["lake_root"]))))
        if counts["rows"] <= 0 or any(v for k, v in counts.items() if k != "rows"):
            raise FactorRepairError("repair_factor_contract_failed")
    elif selected["freq"] is None:
        if any(daily_qfq_contract_rule_counts(connection, output, selected["day"]).values()):
            raise FactorRepairError("repair_daily_contract_failed")
    else:
        # File path in the SQL is the logical formal target, even for staging candidates.
        from orchestrator.defs.duckdb_sql import duckdb_string
        source = f"(SELECT *, {duckdb_string(target)} AS filename FROM {read_parquet(output, hive_partitioning=False)})"
        dates = selected["profiles"][0]["dates"]
        row = connection.execute(minute_qfq_counts_sql(gold_source=source, partition_key=dates, freq=selected["freq"])).fetchone()
        if row[0] <= 0 or any(row[1:]):
            raise FactorRepairError("repair_minute_contract_failed")
        from orchestrator.defs.stk_mins_qfq import (
            build_canonical_gold_stk_mins_qfq_coverage_identities_sql,
            gold_stk_mins_qfq_source_freq,
        )
        profile = selected["profiles"][0]
        expected = build_canonical_gold_stk_mins_qfq_coverage_identities_sql(
            silver_paths=[inputs.project(paths.silver_stk_mins_path(Path(plan["lake_root"]),gold_stk_mins_qfq_source_freq(selected["freq"]),d)) for d in dates],
            trade_adj_factor_paths=[inputs.project(paths.silver_adj_factor_path(Path(plan["lake_root"]),d)) for d in dates],
            as_of_adj_factor_paths=[inputs.project(paths.silver_adj_factor_path(Path(plan["lake_root"]),profile["as_of"]))],
            target_freq=selected["freq"],partition_keys=dates,stock_codes=[profile["code"]])
        if any(connection.execute(minute_qfq_identity_coverage_counts_sql(gold_source=source,
            expected_identity_sql=expected,partition_key=dates)).fetchone()):
            raise FactorRepairError("repair_minute_source_coverage_failed")


def build_repair_target_candidate(connection, plan, unit, target, *, cancel=None, audit=False):
    record_path = repair_record_path(Path(plan["run_root"]), target, Path(plan["lake_root"]))
    if not audit and record_path.exists() and "record_hash" in json.loads(record_path.read_text()):
        record = read_repair_candidate_record(plan, target)
        inputs = RepairCandidateInputs(connection, plan, cancel)
        for path in record.get("input_paths", ()):
            inputs.frozen(Path(path))
        if str(target) not in record.get("input_paths", ()):
            raise FactorRepairError("repair_candidate_record_invalid")
        for path, fingerprint in record.get("overlay_hashes", {}).items():
            if read_repair_candidate_record(plan, Path(path))["candidate_sha256"] != fingerprint:
                raise FactorRepairError("repair_overlay_drift")
        schema = repair_asset_schema(unit["asset_key"])
        selected = repair_target_scope(plan, unit, target)
        output = target if record["no_op"] else Path(plan["run_root"]) / record["candidate_relative_path"]
        validate_repair_business_file(connection, plan, target, output, selected, inputs, schema)
        return record
    schema, keys, selected, inputs = prepare_repair_replacement(connection, plan, unit, target, cancel=cancel)
    validate = lambda c, p, _day: validate_repair_business_file(c, plan, target, p, selected, inputs, schema)
    if audit:
        record = read_repair_candidate_record(plan, target)
        output = target if record["no_op"] else Path(plan["run_root"]) / record["candidate_relative_path"]
        validate(connection, output, selected["day"])
        columns = _columns(schema)
        computed_changed = _scalar(connection, f"SELECT count(*) FROM (SELECT {columns} FROM repair_replacement EXCEPT ALL SELECT {columns} FROM {read_parquet(target, hive_partitioning=False)})")
        if (computed_changed != record["changed_stock_rows"] or bool(computed_changed) == record["no_op"]
                or record["candidate_rows"] != _scalar(connection, f"SELECT count(*) FROM {read_parquet(output, hive_partitioning=False)}")):
            raise FactorRepairError("repair_candidate_record_invalid")
        join = " AND ".join(f'o."{k}" IS NOT DISTINCT FROM a."{k}"' for k in keys)
        for left, right in ((output, target), (target, output)):
            def retained(p):
                return f"SELECT {columns} FROM {read_parquet(p, hive_partitioning=False)} o WHERE NOT EXISTS(SELECT 1 FROM repair_approved a WHERE {join})"
            if _scalar(connection, f"SELECT count(*) FROM ({retained(left)} EXCEPT ALL {retained(right)})"):
                raise FactorRepairError("repair_retained_rows_changed")
        actual = f"SELECT {columns} FROM {read_parquet(output, hive_partitioning=False)} o WHERE EXISTS(SELECT 1 FROM repair_approved a WHERE {join})"
        for left, right in ((actual, "SELECT * FROM repair_replacement"), ("SELECT * FROM repair_replacement", actual)):
            if _scalar(connection, f"SELECT count(*) FROM ({left} EXCEPT ALL {right})"):
                raise FactorRepairError("repair_candidate_value_mismatch")
        for path in inputs.verified:
            if asdict(file_identity(Path(path), cancel=cancel)) != inputs.identities[path]:
                raise FactorRepairError("input_drift")
        return read_repair_candidate_record(plan, target)
    def finalize(record):
        preimage = next(i for i in plan["target_preimages"] if i["path"] == str(target))
        if record["preimage_sha256"] != preimage["sha256"] or asdict(file_identity(target,cancel=cancel)) != preimage:
            raise FactorRepairError("target_drift")
        for path in inputs.verified:
            if asdict(file_identity(Path(path),cancel=cancel)) != inputs.identities[path]:
                raise FactorRepairError("input_drift")
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
            check_repair_storage,
        )
        check_repair_storage(Path(plan["run_root"]),plan=plan)
        complete = {"format_version":1, **record, "input_paths":sorted(inputs.verified),
                    "overlay_hashes":inputs.overlays,
                    "max_source_amount_abs_difference":selected.get("max_source_amount_abs_difference",0)}
        complete["record_hash"] = repair_hash(complete)
        write_candidate_record(Path(plan["run_root"]),complete)
        record.clear(); record.update(complete)
    return build_scoped_file_candidate(connection,lake_root=Path(plan["lake_root"]),
        run_root=Path(plan["run_root"]),target=target,replacement_relation="repair_replacement",
        approved_keys_relation="repair_approved",schema=schema,key_columns=keys,
        plan_hash=plan["plan_hash"],unit_id=repair_hash([plan["plan_hash"],unit["asset_key"],str(target)]),
        asset_key=unit["asset_key"],partition_key=selected["day"] or target.parent.name,
        validator=validate,finalize_record=finalize,cancel=cancel)



def repair_asset_schema(asset):
    from orchestrator.defs.run_contracts.asset_column_schemas import (
        GOLD_STK_MINS_QFQ_SCHEMA,
        GOLD_STOCK_DAILY_QFQ_SCHEMA,
        RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
        SILVER_ADJ_FACTOR_SCHEMA,
    )
    if asset not in PRICE_REPAIR_ASSETS:
        raise FactorRepairError("repair_phase_not_supported")
    return (RAW_TUSHARE_ADJ_FACTOR_SCHEMA if asset == "raw_tushare_adj_factor" else
            SILVER_ADJ_FACTOR_SCHEMA if asset == "silver_adj_factor" else
            GOLD_STOCK_DAILY_QFQ_SCHEMA if asset == "gold_stock_daily_qfq" else GOLD_STK_MINS_QFQ_SCHEMA)
