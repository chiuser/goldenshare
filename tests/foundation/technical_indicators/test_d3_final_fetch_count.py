"""LLD 19.30: retain real calculate/SQL/COUNT, corrupt only final fetch delivery.

The existing producer-shaped three-file fixture supplies prices 10/12/11.
Only the final select_result cursor omits or repeats its last row. This reaches
the collector's COUNT comparison and the executor's max_rows check separately;
neither earlier batch checks nor a mocked COUNT can substitute for them.
"""

from dataclasses import replace
from datetime import date
import json

import duckdb
import pytest

from d3_support import ObservedService, REPORT, d3_data, request
from src.foundation.technical_indicators.errors import OutputContractError
from src.foundation.technical_indicators.executor import DuckDBExecutor


def test_calculate_final_fetch_count_and_cleanup(d3_data, monkeypatch):
    state = d3_data
    with state.case("calculate_final_fetch_count_and_cleanup"):
        before = (state.input_rows, state.sql_rows, state.real_controls)
        details = {"status": "running", "calls": []}
        primary_error = None
        opened = []
        current = None
        original_open = ObservedService._open_execution
        original_read = DuckDBExecutor.read_result

        def observe_open(self, control):
            connection, executor = original_open(self, control)
            opened.append((connection, executor, control))
            return connection, executor

        class CursorView:
            def __init__(self, actual, entry):
                self.actual, self.entry = actual, entry
                self.description = actual.description
                self.calls = 0

            def fetchmany(self, count):
                assert 0 < count <= 8192
                batch = self.actual.fetchmany(count)
                self.calls += 1
                self.entry["native_fetch_sizes"].append(len(batch))
                if self.calls == 1:
                    assert len(batch) == 3
                    if self.entry["mode"] == "short":
                        batch = batch[:-1]
                    elif self.entry["mode"] == "over":
                        batch = [*batch, batch[-1]]
                self.entry["delivered_fetch_sizes"].append(len(batch))
                return batch

        class ConnectionView:
            def __init__(self, actual, entry):
                self.actual, self.entry = actual, entry

            def execute(self, sql, bindings):
                actual = self.actual.execute(sql, bindings)
                self.entry["real_final_query_calls"] += 1
                return CursorView(actual, self.entry)

        def observe_read(self, step, **kwargs):
            if step.name == "count_tail":
                rows = original_read(self, step, **kwargs)
                current["count_results"].append(rows)
                return rows
            if step.name != "select_result":
                return original_read(self, step, **kwargs)
            assert kwargs["max_rows"] == 3
            connection = self.connection
            self.connection = ConnectionView(connection, current)
            try:
                return original_read(self, step, **kwargs)
            finally:
                self.connection = connection

        monkeypatch.setattr(ObservedService, "_open_execution", observe_open)
        monkeypatch.setattr(DuckDBExecutor, "read_result", observe_read)
        selected = request(period="day", adjustment="none", limit=3)
        config = replace(state.config, goldenshare_lake_root=str(state.literal_root))
        try:
            for mode, actual_count in (("normal", 3), ("short", 2), ("over", 4)):
                current = {
                    "mode": mode, "status": "running", "result_returned": False,
                    "count_results": [], "real_final_query_calls": 0,
                    "native_fetch_sizes": [], "delivered_fetch_sizes": [],
                    "closed_connection_probe": {"status": "not_started"},
                }
                details["calls"].append(current)
                call_index, opened_before = len(state.calls), len(opened)
                returned = None
                call_error = None
                try:
                    if mode == "normal":
                        returned = state.run(selected, real=False, config=config)
                        current["result_returned"] = True
                        result, _, _ = returned
                        assert result.times == (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7))
                        assert result.range.count == 3 and result.msg == ""
                        assert len(result.calculations) == 1
                        item = result.calculations[0]
                        assert (item.instance_id, item.calculation_id, item.algorithm_version) == (
                            "price", "price", "1.0.0",
                        )
                        assert dict(item.parameters) == {}
                        assert dict(item.fields) == {
                            "open": (10.0, 12.0, 11.0), "high": (10.0, 12.0, 11.0),
                            "low": (10.0, 12.0, 11.0), "close": (10.0, 12.0, 11.0),
                            "volume": (100.0, 100.0, 100.0), "amount": (1000.0, 1000.0, 1000.0),
                        }
                        assert result.statistics.sql_processed_rows == 41
                    else:
                        with pytest.raises(OutputContractError) as caught:
                            returned = state.run(selected, real=False, config=config)
                            current["result_returned"] = True
                        error = caught.value
                        current.update(error_type=type(error).__name__, reason=error.reason,
                                       stage=error.stage, diagnostics=error.diagnostics,
                                       cleanup_notes=list(getattr(error, "__notes__", ())))
                        assert type(error) is OutputContractError
                        assert error.reason == "fetch_count_mismatch" and error.stage == "final_fetch"
                        assert error.diagnostics == {"expected_count": 3, "actual_count": actual_count}
                        assert not getattr(error, "__notes__", ())
                        assert returned is None and not current["result_returned"]
                    assert current["count_results"] == [((3,),)]
                    assert current["real_final_query_calls"] == 1
                    assert current["native_fetch_sizes"] == ([3] if mode == "over" else [3, 0])
                    assert current["delivered_fetch_sizes"] == ([4] if mode == "over" else [actual_count, 0])
                except BaseException as error:
                    call_error = error
                    current.update(status="failed", unexpected_error_type=type(error).__name__,
                                   unexpected_error=str(error))
                    raise
                finally:
                    try:
                        assert len(opened) == opened_before + 1
                        connection, executor, control = opened[-1]
                        call = state.calls[call_index]
                        final_reads = [item for item in executor.statistics if item.step_name == "select_result"]
                        assert len(final_reads) == 1
                        final_read = final_reads[0]
                        current.update(
                            call_status=call["status"], source_rows=call["source_rows"],
                            batches=call["batches"], source_open_calls=call["source_open_calls"],
                            sql_logical_rows=executor.sql_processed_rows,
                            final_read={"output_rows": final_read.output_rows, "failed": final_read.failed,
                                        "logical_input_rows": final_read.logical_input_rows},
                            connection_restored=executor.connection is connection,
                            live_tables=sorted(executor._live_tables), live_arrow=sorted(executor._live_arrow),
                            cleanup_ready=control.cleanup_ready, resources_released_at=control.resources_released_at,
                        )
                        probe = current["closed_connection_probe"]
                        probe["status"] = "running"
                        with pytest.raises(duckdb.ConnectionException, match="closed") as closed:
                            state.query(connection, "final_count_closed_connection_probe", "SELECT 1", rows=1)
                        probe.update(status="passed_expected_error", error_type=type(closed.value).__name__,
                                     error=str(closed.value), logical_input_rows=1)
                        assert call["source_rows"] == 3 and call["batches"] == [3]
                        assert call["source_open_calls"] == 1
                        assert call["status"] == ("passed" if mode == "normal" else "failed")
                        assert executor.sql_processed_rows == 41
                        assert final_read.logical_input_rows == 3 and final_read.output_rows == actual_count
                        assert final_read.failed is (mode == "over")
                        assert executor.connection is connection and not executor._executing
                        assert not executor._live_tables and not executor._live_arrow
                        assert control.cleanup_ready and control.resources_released_at is not None
                        current["cleanup_status"] = "passed"
                        if call_error is None:
                            current["status"] = "passed"
                    except BaseException as error:
                        current.update(status="failed", cleanup_status="failed", cleanup_error=str(error))
                        if call_error is None:
                            raise
                        call_error.add_note(f"Final count cleanup assertion: {type(error).__name__}: {error}")
            assert (state.input_rows - before[0], state.sql_rows - before[1],
                    state.real_controls - before[2]) == (9, 126, 0)
            details["status"] = "passed"
        except BaseException as error:
            primary_error = error
            details.update(status="failed", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            details["actual_increment"] = {
                "input_rows": state.input_rows - before[0], "sql_logical_rows": state.sql_rows - before[1],
                "real_controls": state.real_controls - before[2],
            }
            try:
                (REPORT / "final_fetch_count_details_20261026.json").write_text(
                    json.dumps(details, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8",
                )
            except BaseException as error:
                if primary_error is None:
                    raise
                primary_error.add_note(f"Final count evidence write: {type(error).__name__}: {error}")
