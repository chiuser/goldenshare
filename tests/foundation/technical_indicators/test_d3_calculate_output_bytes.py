"""LLD 19.29: three direct calculate calls share three owned daily literals.

The Parquet producer contract and 10/12/11 values come from the existing
prepare_required_literals fixture. The complete expected library JSON below is
an independent LLD literal; neither product encoding nor result mapping builds
it. Only the control clock is substituted. Source, Arrow, SQL, output encoding
and connection cleanup remain real, with no real interrupt-control thread.
"""

from dataclasses import asdict, replace
from datetime import date
import json

import duckdb
import pytest

import d3_support
from d3_support import D3Control, ObservedService, REPORT, d3_data, request
from src.foundation.technical_indicators.errors import ResourceLimitError


def test_calculate_utf8_limits_and_cleanup(d3_data, monkeypatch):
    state = d3_data
    with state.case("calculate_utf8_limits_and_cleanup"):
        before = (state.input_rows, state.sql_rows, state.real_controls)
        details = {"status": "running", "calls": []}
        primary_error = None
        try:
            paths = tuple(
                state.literal_root
                / f"silver/quote/stock_daily/trade_date={day}/part-000.parquet"
                for day in ("2026-01-05", "2026-01-06", "2026-01-07")
            )
            source_files = [{"path": str(path), "bytes": path.stat().st_size} for path in paths]
            source_file_bytes = sum(item["bytes"] for item in source_files)
            details["source_files"] = source_files
            # Independent count: original 38 service rows plus three one-row
            # locate_stage steps. Scalar metadata queries keep the established
            # zero logical-row accounting. No warmup SQL is needed for price.
            expected = {
                "kernel_version": "2.0.0",
                "series": {
                    "security_type": "stock", "ts_code": "600000.SH", "period": "day",
                    "adjustment": "none", "timezone": "Asia/Shanghai", "price_unit": "CNY",
                    "volume_unit": "lot", "amount_unit": "thousand_CNY",
                },
                "requested": {"start": None, "end": None, "before": None, "limit": 1000},
                "source": {
                    "id": "lake_stock_daily", "contract_version": "1", "input_adjustment": "none",
                    "history_start": None, "read_start": "2026-01-05", "read_end": "2026-01-07",
                    "available_through": None,
                },
                "price_adjustment": {
                    "input_basis_rule": None, "output_basis_rule": None,
                    "basis_date": None, "basis_value": None, "converted": False,
                    "formula_version": "1.0.0",
                },
                "times": ["2026-01-05", "2026-01-06", "2026-01-07"],
                "source_as_of": None,
                "calculations": [{
                    "instance_id": "price", "calculation_id": "price", "algorithm_version": "1.0.0",
                    "parameters": {},
                    "fields": {
                        "open": [10.0, 12.0, 11.0], "high": [10.0, 12.0, 11.0],
                        "low": [10.0, 12.0, 11.0], "close": [10.0, 12.0, 11.0],
                        "volume": [100.0, 100.0, 100.0], "amount": [1000.0, 1000.0, 1000.0],
                    },
                }],
                "range": {"actual_start": "2026-01-05", "actual_end": "2026-01-07", "count": 3},
                "statistics": {
                    "source_rows": 3, "sql_processed_rows": 41, "source_files": 3,
                    "source_file_bytes": source_file_bytes, "locator_rows": 3,
                    "price_conversion_batches": 0, "elapsed_ms": 0.0,
                },
                "msg": "",
            }
            expected_bytes = json.dumps(
                expected, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ).encode("utf-8")
            byte_count = len(expected_bytes)
            details.update(expected_payload=expected, expected_utf8_bytes=byte_count,
                           thresholds=[byte_count + 1, byte_count, byte_count - 1])

            class FixedClock(D3Control):
                clock = staticmethod(lambda: 0.0)

                def __init__(self, config):
                    super().__init__(config)
                    self.arrived_at = 0.0

            # D3State's monotonic budget clock is deliberately untouched.
            monkeypatch.setattr(d3_support, "D3Control", FixedClock)
            opened = []
            original_open = ObservedService._open_execution

            def observe_open(self, control):
                connection, executor = original_open(self, control)
                opened.append((self, connection, executor, control))
                return connection, executor

            monkeypatch.setattr(ObservedService, "_open_execution", observe_open)

            def date_json(value):
                if type(value) is date:
                    return value.isoformat()
                raise TypeError(f"Unexpected library result value: {type(value).__name__}")

            selected = request(period="day", adjustment="none", limit=1000)
            for index, threshold in enumerate((byte_count + 1, byte_count, byte_count - 1)):
                entry = {"index": index + 1, "threshold": threshold, "status": "running",
                         "result_returned": False, "actual_matches_expected": None,
                         "closed_connection_probe": {"status": "not_started"}}
                details["calls"].append(entry)
                call_index = len(state.calls)
                opened_before = len(opened)
                returned = None
                call_error = None
                try:
                    config = replace(state.config, goldenshare_lake_root=str(state.literal_root),
                                     max_output_bytes=threshold)
                    if index < 2:
                        returned = state.run(selected, real=False, config=config)
                        entry["result_returned"] = True
                        result, _, _ = returned
                        actual = asdict(result)
                        for calculation in actual["calculations"]:
                            calculation["parameters"] = dict(calculation["parameters"])
                            calculation["fields"] = dict(calculation["fields"])
                        actual_bytes = json.dumps(
                            actual, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
                            default=date_json,
                        ).encode("utf-8")
                        entry.update(actual_utf8_bytes=len(actual_bytes),
                                     actual_matches_expected=actual_bytes == expected_bytes,
                                     actual_payload=json.loads(actual_bytes))
                        assert actual_bytes == expected_bytes
                        assert result.statistics.sql_processed_rows == 41
                    else:
                        with pytest.raises(ResourceLimitError) as caught:
                            returned = state.run(selected, real=False, config=config)
                            entry["result_returned"] = True
                        entry.update(error_type=type(caught.value).__name__, error=str(caught.value),
                                     cleanup_notes=list(getattr(caught.value, "__notes__", ())))
                        assert type(caught.value) is ResourceLimitError
                        assert not getattr(caught.value, "__notes__", ())
                        assert returned is None and not entry["result_returned"]
                except BaseException as error:
                    call_error = error
                    entry.update(status="failed", error_type=type(error).__name__, error=str(error))
                    raise
                finally:
                    try:
                        assert len(opened) == opened_before + 1
                        _, connection, executor, control = opened[-1]
                        call = state.calls[call_index]
                        entry.update(
                            source_rows=call["source_rows"], batches=call["batches"],
                            source_open_calls=call["source_open_calls"],
                            sql_logical_rows=executor.sql_processed_rows,
                            live_tables=sorted(executor._live_tables), live_arrow=sorted(executor._live_arrow),
                            cleanup_ready=control.cleanup_ready,
                            resources_released_at=control.resources_released_at,
                        )
                        probe = entry["closed_connection_probe"]
                        probe["status"] = "running"
                        with pytest.raises(duckdb.ConnectionException, match="closed") as closed:
                            state.query(connection, "closed_connection_probe", "SELECT 1", rows=1)
                        probe.update(status="passed_expected_error", error_type=type(closed.value).__name__,
                                     error=str(closed.value), logical_input_rows=1)
                        assert call["source_rows"] == 3 and call["batches"] == [3]
                        assert call["source_open_calls"] == 1
                        assert executor.sql_processed_rows == 41
                        assert not executor._live_tables and not executor._live_arrow
                        assert control.cleanup_ready and control.resources_released_at == 0.0
                        entry["cleanup_status"] = "passed"
                        if call_error is None:
                            entry["status"] = "passed"
                    except BaseException as error:
                        entry.update(status="failed", cleanup_status="failed", cleanup_error_type=type(error).__name__,
                                     cleanup_error=str(error))
                        probe = entry["closed_connection_probe"]
                        if probe["status"] == "running":
                            probe.update(status="failed", error_type=type(error).__name__, error=str(error))
                        if call_error is None:
                            raise
                        call_error.add_note(f"Output boundary cleanup assertion: {type(error).__name__}: {error}")

            assert len(opened) == 3 and len(details["calls"]) == 3
            assert (state.input_rows - before[0], state.sql_rows - before[1],
                    state.real_controls - before[2]) == (9, 126, 0)
            details["status"] = "passed"
        except BaseException as error:
            primary_error = error
            details.update(status="failed", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            details["actual_increment"] = {
                "input_rows": state.input_rows - before[0],
                "sql_logical_rows": state.sql_rows - before[1],
                "real_controls": state.real_controls - before[2],
            }
            try:
                (REPORT / "calculate_output_bytes_details_20261026.json").write_text(
                    json.dumps(details, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except BaseException as error:
                if primary_error is None:
                    raise
                primary_error.add_note(f"Output boundary evidence write: {type(error).__name__}: {error}")
