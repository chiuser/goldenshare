from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


def load_frozen_inputs(root: Path) -> tuple[dict[int, list[XxmBar]], dict]:
    manifest = json.loads((root / "historical_withdrawal_full_timeline_20261013.json").read_text())
    merged: dict[int, dict[str, dict]] = {60: {}, 90: {}, 120: {}}
    for relative, sha in manifest["frozen_definitions"]["inputs"].items():
        path = root / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError(f"Frozen input hash changed: {relative}")
        prefix = path.stem.split("_")[0]
        freq = int(prefix) if prefix.isdigit() else int(path.stem.split("_")[-1])
        with path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                stamp = row.get("trade_time") or row.get("time")
                if not stamp:
                    raise ValueError("Frozen minute endpoint missing")
                previous = merged[freq].get(stamp)
                if previous is not None:
                    if float(previous["close"]) != float(row["close"]) or any(
                        abs(float(previous[key]) - float(row[key])) >= 1e-8 for key in ("dif", "hist")
                    ):
                        raise ValueError("Frozen source overlap differs")
                else:
                    merged[freq][stamp] = row
    series = {}
    for freq, rows in merged.items():
        series[freq] = [XxmBar(stamp.replace(" ", "T") + "+08:00", float(row["close"]), float(row["dif"]),
                              float(row.get("dea") or (float(row["dif"]) - float(row["hist"]) / 2)), float(row["hist"]))
                        for stamp, row in sorted(rows.items())]
    return series, manifest
