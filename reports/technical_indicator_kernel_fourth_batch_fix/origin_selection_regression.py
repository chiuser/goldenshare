"""Narrow selection regression; no Parquet, DuckDB or indicator execution.

Only metadata/key-reading methods are substituted. The actual _select method
and PriceReadSelection constructor execute. Counts describe an abstract ordered
source; no price rows or trading-calendar assertions are generated.
"""

import argparse
import ast
from dataclasses import asdict
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys
from time import monotonic
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    started = monotonic()
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path)
    args = parser.parse_args()
    from src.foundation.clients.local_lake.technical_indicator_price_locator import LakePriceLocator, _Group
    from src.foundation.technical_indicators.errors import ResourceLimitError
    from src.foundation.technical_indicators.sources.contracts import PriceReadSelection

    path = ROOT / "src/foundation/clients/local_lake/technical_indicator_price_locator.py"
    ast.parse(path.read_text())
    first = date(2000, 1, 1)

    def run(select, *, rows, targets, warmup, capacity, origin_required=False):
        # The ranks below are independent, ordered positions, not OHLC values.
        locator = object.__new__(LakePriceLocator)
        locator.source = SimpleNamespace(_config=SimpleNamespace(max_input_rows=capacity))
        locator.requirement = SimpleNamespace(
            request=SimpleNamespace(period="day", limit=1000),
            history=SimpleNamespace(warmup_rows=warmup, requires_source_origin=origin_required),
        )
        locator.control = SimpleNamespace(check_active=lambda: None)
        group = _Group(Path("owned-metadata-only.parquet"), 0, rows, targets,
                       first, first + timedelta(days=rows - 1))
        locator._open_metadata = lambda *args: SimpleNamespace(
            num_row_groups=1, row_group=lambda index: object())
        locator._close_metadata = lambda: None
        locator._may_match = lambda *args: True
        locator._check_group_bytes = lambda *args: None
        locator._count_group = lambda *args: group
        locator._bounds = lambda group, ranks, *args: {
            rank: first + timedelta(days=rank - 1) for rank in ranks}
        try:
            paths, selection = select(locator, (group.path,), None, (), ())
        except ResourceLimitError:
            return {"error": "ResourceLimitError"}
        assert paths == (group.path,)
        assert selection.row_groups == ((0,),)
        assert selection.read_end == selection.target_end == group.last
        assert selection.target_start == first + timedelta(days=rows - selection.target_rows)
        assert selection.read_start == first + timedelta(
            days=rows - selection.target_rows - selection.preceding_rows)
        return {"target_rows": selection.target_rows,
                "input_rows": selection.target_rows + selection.preceding_rows,
                "preceding_rows": selection.preceding_rows,
                "reached_source_origin": selection.reached_source_origin}

    cases = (
        ("oldest_group_4000_select_1500", dict(rows=4000, targets=4000, warmup=500, capacity=1500000),
         dict(target_rows=1000, input_rows=1500, preceding_rows=500, reached_source_origin=False)),
        ("oldest_group_4000_capacity_2000", dict(rows=4000, targets=4000, warmup=500, capacity=2000),
         dict(target_rows=1000, input_rows=1500, preceding_rows=500, reached_source_origin=False)),
        ("short_target_from_start_keeps_only_550", dict(rows=4000, targets=50, warmup=500, capacity=1500000),
         dict(target_rows=50, input_rows=550, preceding_rows=500, reached_source_origin=False)),
        ("1600_first_page_keeps_1500", dict(rows=1600, targets=1600, warmup=500, capacity=1500000),
         dict(target_rows=1000, input_rows=1500, preceding_rows=500, reached_source_origin=False)),
        ("600_oldest_page_returns_all", dict(rows=600, targets=600, warmup=500, capacity=1500000),
         dict(target_rows=600, input_rows=600, preceding_rows=0, reached_source_origin=True)),
        ("1600_origin_with_long_warmup", dict(rows=1600, targets=1600, warmup=1235, capacity=1600),
         dict(target_rows=1000, input_rows=1600, preceding_rows=600, reached_source_origin=True)),
        ("4000_cannot_fit_origin_in_1600", dict(rows=4000, targets=4000, warmup=1235, capacity=1600),
         dict(error="ResourceLimitError")),
    )
    results = []
    for name, inputs, expected in cases:
        actual = run(LakePriceLocator._select, **inputs)
        assert actual == expected, (name, expected, actual)
        results.append({"case": name, "expected": expected, "actual": actual})
    before = []
    if args.before:
        saved = json.loads(args.before.read_text())
        namespace = {"PriceReadSelection": PriceReadSelection, "ResourceLimitError": ResourceLimitError}
        exec(compile(saved["select_source"], saved["path"] + ":before", "exec"), namespace)
        # Explicitly reproduce the original defect, including the start-bound
        # exhaustion branch. Expected mismatches are intentional, not retries.
        for name, inputs, expected in cases[:3]:
            old = run(namespace["_select"], **inputs)
            assert old != expected, ("Original defect was not reproduced", name)
            before.append({"case": name, "actual_before": old, "expected_after": expected})
    elapsed = monotonic() - started
    assert elapsed < 30, elapsed
    record = {"status": "passed_selection_unit_only", "cases": results,
              "before_defect_reproduced": before, "elapsed_seconds": elapsed,
              "price_input_rows": 0, "sql_logical_rows": 0, "locator_key_rows": 0,
              "real_controls": 0, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "coverage": "Actual selection control flow; metadata and key readers substituted. No file, SQL, indicator or service integration acceptance."}
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
