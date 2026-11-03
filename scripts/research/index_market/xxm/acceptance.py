"""Read saved source values and author readouts; no detector execution or writes."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_source(root: Path, period: str) -> list[XxmBar]:
    path = root / ("daily_source.csv" if period == "day" else f"minute_{period[1:]}_source.csv")
    manifest = json.loads((root / "manifest.json").read_text())
    expected = next(item["sha256"] for item in manifest["files"] if item["name"] == path.name)
    if sha(path) != expected:
        raise ValueError(f"M0 source snapshot changed: {path.name}")
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if period == "day":
        return [XxmBar(r["trade_date"], *(float(r[k]) for k in ("close", "macd_dif_bfq", "macd_dea_bfq", "macd_bfq"))) for r in rows]
    return [XxmBar(r["trade_time"].replace(" ", "T") + "+08:00",
                   *(float(r[k]) for k in ("close", "macd_dif", "macd_dea", "macd"))) for r in rows]


def collect_readouts(root: Path) -> list[dict]:
    """Read the 27 original records; image paths are historical provenance."""
    records = json.loads((root / "software_readouts.json").read_text())
    required = {"period", "time", "image", "imageSha256", "sourceRecord",
                "software", "source", "softwareMinusSource", "sameDisplayedValue"}
    if (type(records) is not list or len(records) != 27
            or any(type(item) is not dict or not required <= item.keys()
                   or type(item["period"]) is not str or type(item["time"]) is not str
                   for item in records)
            or len({(item["period"], item["time"]) for item in records}) != 27):
        raise ValueError("Expected 27 unique saved author readouts")
    return records  # JSON creates a new tree on each call; no shared cache.
