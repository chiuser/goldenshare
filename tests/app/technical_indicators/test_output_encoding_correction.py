"""LLD24.6: final-format encoding only; no source, SQL or real Control.

The literal fields and UTF-8 expectation are independent of the product
encoder. The calculation boundary alone is substituted; preparation, library
return, App admission, encoding, sending and error release stay real.
"""

from dataclasses import replace
from datetime import date
import json
from time import monotonic

import anyio
import pytest

from src.app.runtime.technical_indicators import execution
from src.app.runtime.technical_indicators.admission import AdmissionController
from src.app.runtime.technical_indicators.composition import TechnicalIndicatorRuntime
from src.foundation.config.settings import Settings, technical_indicator_config_from_settings
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.contracts import (
    CalculationInstance, CalculationRequest, CalculationResult, CalculationStatistics,
    CalculationValues, OutputRange, PriceAdjustmentResult, RequestedRange,
    SeriesDescription, SourceResult,
)
from goldenshare_technical_indicators.errors import (
    CalculationCancelledError, CalculationDeadlineError, OutputEncodingError,
    RequestInvalidError, ResourceCleanupError,
)
from goldenshare_technical_indicators.output import encoding
from goldenshare_technical_indicators.service import TechnicalIndicatorService


class _Control:
    def __init__(self, *, config, arrived_at=None):
        self.config, self.clock = config, monotonic
        self.arrived_at = monotonic() if arrived_at is None else arrived_at
        self.work_until = self.arrived_at + (config.total_target_ms-config.cleanup_reserve_ms)/1000
        self.target_finish = self.arrived_at + config.total_target_ms/1000
        self.stop_reason = None

    def request_stop(self, reason):
        if self.stop_reason is None:
            self.stop_reason = reason

    def check_active(self):
        if self.stop_reason == "cancel":
            raise CalculationCancelledError("controlled cancellation")
        if self.stop_reason == "deadline" or monotonic() >= self.work_until:
            raise CalculationDeadlineError("controlled deadline")


def _result():
    day = date(2026, 1, 2)
    return CalculationResult(
        "3.0.0", SeriesDescription("stock", "600000.SH", "day", "none", "Asia/Shanghai",
                                   "CNY", "lot", "thousand_CNY"),
        RequestedRange(None, None, None, 1),
        SourceResult("来源", "1", "none", None, day, day, None),
        PriceAdjustmentResult(None, None, None, None, False, "1.0.0"),
        (day,), None,
        (CalculationValues("ma", "ma", "1.0.0", (("period", 20),), (("value", (None,)),)),),
        OutputRange(day, day, 1), CalculationStatistics(1, 0, 0, 0, 0, 0, 0.0), "",
    )


def _expected_bytes():
    expected = {
        "kernel_version": "3.0.0",
        "series": {"security_type": "stock", "ts_code": "600000.SH", "period": "day",
                   "adjustment": "none", "timezone": "Asia/Shanghai", "price_unit": "CNY",
                   "volume_unit": "lot", "amount_unit": "thousand_CNY"},
        "requested": {"start": None, "end": None, "before": None, "limit": 1},
        "source": {"id": "来源", "contract_version": "1", "input_adjustment": "none",
                   "history_start": None, "read_start": "2026-01-02", "read_end": "2026-01-02",
                   "available_through": None},
        "price_adjustment": {"input_basis_rule": None, "output_basis_rule": None,
                             "basis_date": None, "basis_value": None, "converted": False,
                             "formula_version": "1.0.0"},
        "times": ["2026-01-02"], "source_as_of": None,
        "calculations": [{"instance_id": "ma", "calculation_id": "ma", "algorithm_version": "1.0.0",
                          "parameters": {"period": 20}, "fields": {"value": [None]}}],
        "range": {"actual_start": "2026-01-02", "actual_end": "2026-01-02", "count": 1},
        "statistics": {"source_rows": 1, "sql_processed_rows": 0, "source_files": 0,
                       "source_file_bytes": 0, "locator_rows": 0, "price_conversion_batches": 0,
                       "elapsed_ms": 0.0}, "msg": "",
    }
    return json.dumps(expected, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def test_library_and_http_encode_only_their_final_output(monkeypatch):
    config = technical_indicator_config_from_settings(Settings(_env_file=None))
    selected = CalculationRequest("stock", "600000.SH", "day", (
        CalculationInstance("ma", "ma", {"period": 20}),
    ), adjustment="none", limit=1)
    literal, expected = _result(), _expected_bytes()
    counts = {"prepare": 0, "core": 0, "json": 0, "encode": 0}
    mode = {"failure": None}
    prepare = TechnicalIndicatorService._prepare_calculation
    iter_utf8, encode = encoding._iter_utf8, encoding.encode_response_utf8

    def prepare_once(self, request):
        counts["prepare"] += 1
        return prepare(self, request)

    def core(self, prepared, *, control):
        counts["core"] += 1
        assert prepared.normalized is selected
        assert prepared.instances[0].parameters == (("period", 20),)
        if mode["failure"] == "cleanup":
            raise ResourceCleanupError("literal cleanup failure")
        if mode["failure"] == "nan":
            return replace(literal, calculations=(replace(
                literal.calculations[0], fields=(("value", (float("nan"),)),),
            ),))
        return literal

    def iter_once(*args, **kwargs):
        counts["json"] += 1
        yield from iter_utf8(*args, **kwargs)

    def encode_once(*args, **kwargs):
        counts["encode"] += 1
        return encode(*args, **kwargs)

    monkeypatch.setattr(TechnicalIndicatorService, "_prepare_calculation", prepare_once)
    monkeypatch.setattr(TechnicalIndicatorService, "_calculate_result", core)
    monkeypatch.setattr(encoding, "_iter_utf8", iter_once)
    monkeypatch.setattr(execution, "encode_response_utf8", encode_once)
    monkeypatch.setattr(execution, "ExecutionControl", _Control)

    service = TechnicalIndicatorService(source=object(), registry=create_builtin_registry(),
        config=config, control=_Control(config=config))
    assert service.calculate(selected) is literal
    assert counts == {"prepare": 1, "core": 1, "json": 0, "encode": 0}

    async def http_case(error=None):
        for key in counts:
            counts[key] = 0
        runtime = TechnicalIndicatorRuntime(config, create_builtin_registry(), object(),
                                             AdmissionController(config))
        messages = []
        never = anyio.Event()

        async def receive():
            await never.wait()

        async def send(message):
            messages.append(message)

        try:
            if error is None:
                await execution.execute_http(runtime, selected, arrived_at=monotonic(), receive=receive, send=send)
                assert len(messages) == 2 and messages[1]["body"] == expected
            else:
                with pytest.raises(error):
                    await execution.execute_http(runtime, selected, arrived_at=monotonic(), receive=receive, send=send)
                assert messages == []
            assert not runtime.admission.active_leases
            encoded = 0 if error is ResourceCleanupError else 1
            assert counts == {"prepare": 1, "core": 1, "json": encoded, "encode": encoded}
        finally:
            await runtime.aclose()

    async def scenario():
        await http_case()
        mode["failure"] = "cleanup"
        await http_case(ResourceCleanupError)
        mode["failure"] = "nan"
        await http_case(OutputEncodingError)
        mode["failure"] = None
        runtime = TechnicalIndicatorRuntime(config, create_builtin_registry(), object(), AdmissionController(config))
        calls = []
        acquire = runtime.admission.acquire

        async def observed_acquire(control):
            calls.append(control)
            return await acquire(control)

        monkeypatch.setattr(runtime.admission, "acquire", observed_acquire)
        bad = replace(selected, calculations=(CalculationInstance("ma", "ma", {"period": 0}),))
        try:
            with pytest.raises(RequestInvalidError):
                await execution.execute_library(runtime, bad, arrived_at=monotonic())
            assert calls == []
            assert await execution.execute_library(runtime, selected, arrived_at=monotonic()) is literal
            assert len(calls) == 1 and not runtime.admission.active_leases
        finally:
            await runtime.aclose()

    anyio.run(scenario)
