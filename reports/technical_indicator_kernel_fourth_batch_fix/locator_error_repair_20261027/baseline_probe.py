"""Planned pre-fix evidence only: no prices, SQL, connection or real control."""

import json
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pyarrow as pa

from src.foundation.clients.local_lake.technical_indicator_price_locator import LakePriceLocator
from src.foundation.technical_indicators import CalculationInstance, CalculationRequest
from src.foundation.technical_indicators.calculation.history import HistoryRequirement
from src.foundation.technical_indicators.sources.contracts import ReadRequirement


def main():
    started = monotonic()
    results = []
    request = CalculationRequest("stock", "600000.SH", "day",
        (CalculationInstance("price", "price", {}),), adjustment="none", limit=3)
    requirement = ReadRequirement(request,
        HistoryRequirement(frozenset({"close"}), 0, 0, False, (), "literal"),
        8192, None, None)
    for error in (pa.ArrowInvalid("planned original decode failure"),
                  pa.ArrowMemoryError("planned original allocation failure")):
        source = SimpleNamespace(_root=lambda: Path("/private/tmp"),
            _partition_paths=lambda *args, **kwargs: ())
        control = SimpleNamespace(check_active=lambda: None, cleanup_ready=True)
        locator = LakePriceLocator(source, SimpleNamespace(control=control),
            requirement, read_context=None)

        def fail(*args, **kwargs):
            raise error

        locator._select = fail
        try:
            locator.describe()
        except BaseException as actual:
            assert actual is error, "The original defect is not present as expected"
            results.append({"original_type": type(error).__name__,
                            "actual_type": type(actual).__name__, "same_object": True})
        else:
            raise AssertionError("The planned failing boundary returned success")
        finally:
            locator.close()
        assert locator._closed and not locator._tables and not locator._registrations
    result = {"status": "known_original_defect_confirmed", "cases": results,
              "input_rows": 0, "sql_logical_rows": 0, "locator_rows": 0,
              "real_controls": 0, "elapsed_seconds": monotonic() - started}
    target = Path(__file__).with_name("baseline_result.json")
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
