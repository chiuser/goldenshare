"""Repair the approved DG Shenzhen Component Index daily turnover fields."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io import index_daily_writer as writer
from orchestrator.defs.paths import (
    gold_market_major_indices_daily_path,
    raw_index_daily_path,
    silver_index_daily_path,
    silver_trade_calendar_path,
)

CODE = "399001.SZ"
START = "2023-11-27"
END = "2026-07-06"
CONTROL = "2026-07-07"
PILOT_DATES = (START, END)
DAY_COUNT = 630
LAYERS = {
    "raw_index_daily": raw_index_daily_path,
    "silver_index_daily": silver_index_daily_path,
    "gold_market_major_indices_daily": gold_market_major_indices_daily_path,
}
SHANGHAI = ZoneInfo("Asia/Shanghai")


def load_official_rows(payload: bytes) -> dict[str, dict[str, str]]:
    response = json.loads(payload, parse_float=Decimal)
    data = response["data"]
    if response["code"] != 200 or data["indexCode"] != "399001":
        raise ValueError("Official response must contain daily data for 399001")
    rows = {}
    for values in data["data"]:
        row = dict(zip(data["item"], values, strict=True))
        day = datetime.fromtimestamp(row["timestamp"] / 1000, SHANGHAI).date()
        key = day.isoformat()
        volume = Decimal(row["volume"])
        amount = Decimal(row["amount"])
        close = Decimal(row["close"])
        if key in rows or not all(
            value.is_finite() and value > 0 for value in (volume, amount, close)
        ):
            raise ValueError(f"Duplicate date or invalid official daily values: {key}")
        rows[key] = {
            "vol": str(volume / 100),
            "amount": str(amount / 1000),
            "close": str(close),
        }
    return rows


def approved_dates(connection, lake_root: Path) -> tuple[str, ...]:
    result = connection.execute(
        """SELECT trade_date FROM read_parquet(?, hive_partitioning=false)
        WHERE exchange='SSE' AND is_open AND trade_date BETWEEN ?::DATE AND ?::DATE
        ORDER BY trade_date""",
        [str(silver_trade_calendar_path(lake_root)), START, CONTROL],
    ).fetchall()
    dates = tuple(day.isoformat() for (day,) in result)
    if len(set(dates)) != DAY_COUNT + 1 or len(dates) != DAY_COUNT + 1:
        raise ValueError("Trade calendar differs from the approved 630-day range")
    if (dates[0], dates[-2], dates[-1]) != (START, END, CONTROL):
        raise ValueError("Trade calendar does not match the approved boundary dates")
    return dates


def inspect_partition(connection, path: Path, layer: str, day: str) -> dict:
    relation = read_parquet(path, hive_partitioning=False)
    columns = connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    if [(row[0], row[1]) for row in columns] != [
        (column.name, column.type) for column in writer.SCHEMAS[layer]
    ]:
        raise ValueError(f"{day} {layer}: schema differs from the current contract")
    expected_day = day.replace("-", "") if layer == "raw_index_daily" else day
    row_count, key_count, wrong_date, matches, vol, amount, close, protected = (
        connection.execute(
            f"""WITH source AS MATERIALIZED (SELECT * FROM {relation}),
            masked AS (
                SELECT * REPLACE (
                    CASE WHEN ts_code = '{CODE}' THEN NULL::DOUBLE ELSE vol END AS vol,
                    CASE WHEN ts_code = '{CODE}' THEN NULL::DOUBLE ELSE amount END AS amount
                ) FROM source
            )
            SELECT count(*), count(DISTINCT ts_code),
                   count(*) FILTER (WHERE CAST(trade_date AS VARCHAR) IS DISTINCT FROM ?),
                   count(*) FILTER (WHERE ts_code = '{CODE}'),
                   max(vol) FILTER (WHERE ts_code = '{CODE}'),
                   max(amount) FILTER (WHERE ts_code = '{CODE}'),
                   max(close) FILTER (WHERE ts_code = '{CODE}'),
                   (SELECT sha256(string_agg(to_json(masked), chr(10) ORDER BY ts_code))
                    FROM masked)
            FROM source""",
            [expected_day],
        ).fetchone()
    )
    if row_count != key_count or wrong_date or matches != 1:
        raise ValueError(f"{day} {layer}: date or unique index key mismatch")
    return {
        "row_count": row_count,
        "vol": vol,
        "amount": amount,
        "close": close,
        "protected_sha256": protected,
    }


def same_volume_amount(facts: dict, expected: dict) -> bool:
    precision = Decimal("0.0001")
    return all(
        Decimal(str(facts[field])).quantize(precision, rounding=ROUND_HALF_UP)
        == Decimal(expected[field]).quantize(precision, rounding=ROUND_HALF_UP)
        for field in ("vol", "amount")
    )


def build_plan(
    connection, lake_root: Path, payload: bytes, dates: tuple[str, ...]
) -> dict:
    official = load_official_rows(payload)
    if set(official) != set(dates):
        missing = sorted(set(dates) - official.keys())
        extra = sorted(official.keys() - set(dates))
        raise ValueError(
            f"Official date coverage mismatch: missing={missing} extra={extra}"
        )
    days = {}
    for day in dates:
        source = official[day]
        layers = {}
        for layer, path_for in LAYERS.items():
            path = path_for(lake_root, day)
            identity = writer._identity(path)
            if identity is None:
                raise FileNotFoundError(path)
            facts = inspect_partition(connection, path, layer, day)
            if identity != writer._identity(path):
                raise ValueError(f"{day} {layer}: file changed during planning")
            if abs(Decimal(str(facts["close"])) - Decimal(source["close"])) > Decimal(
                "0.0001"
            ):
                raise ValueError(f"{day} {layer}: official and local close differ")
            layers[layer] = {"path": str(path), "identity": identity, **facts}
        days[day] = {"official": source, "layers": layers}
    control = days.pop(CONTROL)
    if not all(
        same_volume_amount(facts, control["official"])
        for facts in control["layers"].values()
    ):
        raise ValueError(
            "The July 7 control must already match the official volume and amount"
        )
    return {
        "index": CODE,
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "days": days,
        "control": control,
    }


def validate_output(
    connection, path: Path, layer: str, day: str, original: dict, source: dict
):
    facts = inspect_partition(connection, path, layer, day)
    if any(facts[key] != original[key] for key in ("row_count", "protected_sha256")):
        raise ValueError(
            f"{day} {layer}: a field outside the approved replacement changed"
        )
    if not same_volume_amount(facts, source):
        raise ValueError(
            f"{day} {layer}: volume or amount differs from the official value"
        )
    return facts


def verify_original(path: Path, original: dict, *, layer: str, day: str):
    if str(path) != original["path"] or writer._identity(path) != original["identity"]:
        raise ValueError(f"{day} {layer}: original file differs from the frozen plan")


def prepare_day(
    connection, lake_root: Path, directory: Path, day: str, entry: dict
) -> dict:
    ready_path = directory / "prepared.json"
    if ready_path.is_file():
        return json.loads(ready_path.read_text())
    directory.mkdir(parents=True, exist_ok=True)
    hashes = {}
    source = entry["official"]
    for layer, path_for in LAYERS.items():
        target = path_for(lake_root, day)
        original = entry["layers"][layer]
        verify_original(target, original, layer=layer, day=day)
        candidate = directory / f"{layer}.parquet"
        sql = f"""SELECT * REPLACE (
            CASE WHEN ts_code = '{CODE}' THEN CAST(? AS DOUBLE) ELSE vol END AS vol,
            CASE WHEN ts_code = '{CODE}' THEN CAST(? AS DOUBLE) ELSE amount END AS amount
        ) FROM {read_parquet(target, hive_partitioning=False)}"""
        connection.execute(
            copy_query_to_parquet(sql, candidate),
            [Decimal(source["vol"]), Decimal(source["amount"])],
        )
        validate_output(connection, candidate, layer, day, original, source)
        verify_original(target, original, layer=layer, day=day)
        with candidate.open("rb") as fh:
            os.fsync(fh.fileno())
        hashes[layer] = writer._digest(candidate)
    writer._save(ready_path, hashes)
    return hashes


def audit_day(
    connection, lake_root: Path, run_dir: Path, day: str, entry: dict
) -> dict:
    receipt = json.loads((run_dir / day / "complete.json").read_text())
    results = {}
    for layer, path_for in LAYERS.items():
        target = path_for(lake_root, day)
        if writer._digest(target) != receipt[layer]:
            raise ValueError(
                f"{day} {layer}: formal file differs from the completion record"
            )
        results[layer] = validate_output(
            connection, target, layer, day, entry["layers"][layer], entry["official"]
        )
    return results


def audit_control(connection, lake_root: Path, plan: dict):
    for layer, path_for in LAYERS.items():
        target = path_for(lake_root, CONTROL)
        original = plan["control"]["layers"][layer]
        verify_original(target, original, layer=layer, day=CONTROL)
        validate_output(
            connection, target, layer, CONTROL, original, plan["control"]["official"]
        )


def apply_day(
    connection, lake_root: Path, run_dir: Path, plan_hash: str, day: str, entry: dict
):
    directory = run_dir / day
    complete = directory / "complete.json"
    if complete.is_file():
        return audit_day(connection, lake_root, run_dir, day, entry)
    prepared = prepare_day(connection, lake_root, directory, day, entry)
    results = {}
    hashes = {}
    for layer, path_for in LAYERS.items():
        target = path_for(lake_root, day)
        candidate = directory / f"{layer}.parquet"
        original = entry["layers"][layer]
        if writer._digest(candidate) != prepared[layer]:
            raise ValueError(f"{day} {layer}: prepared file changed")

        def validate_before_replace(
            db, output, *, target=target, original=original, layer=layer
        ):
            verify_original(target, original, layer=layer, day=day)
            validate_output(db, output, layer, day, original, entry["official"])

        writer.write_index_daily_partition(
            connection,
            f"SELECT * FROM {read_parquet(candidate, hive_partitioning=False)}",
            dataset=layer,
            partition_key=day,
            target_path=target,
            source_paths=(candidate,),
            expected_rows=original["row_count"],
            publication_id=plan_hash,
            additional_identity=(CODE, day, prepared[layer]),
            candidate_validator=validate_before_replace,
        )
        results[layer] = validate_output(
            connection, target, layer, day, original, entry["official"]
        )
        hashes[layer] = writer._digest(target)
    writer._save(complete, hashes)
    for layer in LAYERS:
        (directory / f"{layer}.parquet").unlink()
    return results
