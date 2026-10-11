"""Literal, offline v1 Prod wire fixtures. Never import the Prod encoder."""

import hashlib
import json
from copy import deepcopy

from orchestrator.defs.run_contracts.stock_weekly_adj_delivery import DeliveryHeader

BATCH = "50ea35d4-a18e-41e9-84b3-32e0487cfb3a"
POINT = "1" * 64
HISTORY = "2" * 64


def wire_digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def source_row(day="20261009", code="000001.SZ", qfq="9.0000"):
    return {
        "ts_code": code,
        "trade_date": day,
        "end_date": "20261009",
        "freq": "week",
        "open": "10.0000",
        "high": "12.0000",
        "low": "8.0000",
        "close": "11.0000",
        "pre_close": "10.0000",
        "open_qfq": "8.0000",
        "high_qfq": "10.0000",
        "low_qfq": "6.0000",
        "close_qfq": qfq,
        "open_hfq": None,
        "high_hfq": "20.0000",
        "low_hfq": "12.0000",
        "close_hfq": "18.0000",
        "vol": "1234567890123456.1234",
        "amount": "9999999999999999.9999",
        "change": "1.0000",
        "pct_chg": "10.0000",
    }


def delivery_fixture(*, historical_only=False, empty=False):
    point = {
        "unit_id": POINT,
        "trade_date": "2026-10-09",
        "params": {"freq": "week", "trade_date": "20261009"},
        "progress": {"unit_kind": "point_week"},
    }
    history = {
        "unit_id": HISTORY,
        "trade_date": None,
        "params": {
            "freq": "week",
            "ts_code": "000001.SZ",
            "start_date": "20100101",
            "end_date": "20261009",
        },
        "progress": {"unit_kind": "stock_history"},
    }
    units = [history] if historical_only else [point, history]

    def record(kind, unit_id, revision, payload, **extra):
        return {
            "revision": revision,
            "contract_version": 1,
            "batch_id": BATCH,
            "unit_id": unit_id,
            "record_kind": kind,
            "intent": {"mode": "manual_revision", "bootstrap": False},
            "outcome": "published",
            "unit_kind": None,
            "cutoff_week": "2026-10-09",
            "start_date": None,
            "end_date": None,
            "ts_code": None,
            "payload": payload,
            "rows_received": 0,
            "rows_unique": 0,
            "rows_written": 0,
            "rows_preserved": 0,
            "payload_digest": wire_digest(payload),
            "scope_digest": "b" * 64,
            **extra,
        }

    records = {
        ("plan", "plan"): record(
            "plan",
            "plan",
            1,
            {
                "units": units,
                "execution_context": {"contract_digest": "a" * 64},
            },
        )
    }
    summaries, total_bytes, total_rows = [], 0, 0
    for revision, unit in enumerate(units, 2):
        rows = (
            []
            if empty
            else [source_row(qfq="10.0000")]
            if unit is point
            else [source_row(day="20200228"), source_row()]
            if not historical_only
            else [source_row(day="20200228")]
        )
        payload = {"rows": rows}
        n = len(rows)
        item = record(
            "unit",
            unit["unit_id"],
            revision,
            payload,
            unit_kind=unit["progress"]["unit_kind"],
            rows_received=n,
            rows_unique=n,
            rows_written=n,
            ts_code=None if unit is point else "000001.SZ",
            start_date=None if unit is point else "2010-01-01",
            end_date=None if unit is point else "2026-10-09",
        )
        records[("unit", unit["unit_id"])] = item
        summaries.append({"unit_id": unit["unit_id"], "digest": item["payload_digest"]})
        total_rows += n
        total_bytes += len(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )
    revision = len(units) + 2
    control = {
        "unit_count": len(units),
        "total_payload_bytes": total_bytes,
        "units_digest": wire_digest(summaries),
        "bootstrap": False,
        "contract_digest": "a" * 64,
        "max_input_week": None
        if empty
        else "2020-02-28"
        if historical_only
        else "2026-10-09",
    }
    closure = record(
        "batch_closed",
        "batch_closed",
        revision,
        {"header": control, "unit_ids": [u["unit_id"] for u in units]},
        rows_received=total_rows,
        rows_unique=total_rows,
        rows_written=total_rows,
    )
    records[("batch_closed", revision)] = closure
    header = DeliveryHeader(
        **{
            **{
                n: closure[n]
                for n in DeliveryHeader.__dataclass_fields__
                if n != "header"
            },
            "header": control,
        }
    )
    return header, records


class OfflineDeliveryReader:
    def __init__(self, records):
        self.records, self.calls = records, []

    def read_record(self, header, kind, identity, **kwargs):
        self.calls.append((kind, identity))
        return deepcopy(self.records[kind, identity])

    def closed_batch_header(self, batch_id, revision, **kwargs):
        closure = self.records["batch_closed", revision]
        assert closure["batch_id"] == batch_id
        return DeliveryHeader(
            **{
                **{
                    n: closure[n]
                    for n in DeliveryHeader.__dataclass_fields__
                    if n != "header"
                },
                "header": deepcopy(closure["payload"]["header"]),
            }
        )
