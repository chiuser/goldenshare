"""Expansion LLD 4.1: strict identities and complete five-period DTOs.

Fixtures spell out the current internal/public field contracts. Business facts
are literal: one zero-histogram completed bar has NONE and ZERO_WAVE. The empty
condition identity uses the registered canonical JSON formula independently;
neither a calculator, schema nor response projector supplies expected facts.
"""
from copy import deepcopy
import hashlib
import json

import pytest
from pydantic import ValidationError

from src.biz.schemas.wealth.market.index_detail_xxm import (
    InternalXxmResponseDto, XxmResponseDto, XxmDebugResponseDto,
)
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import (
    InternalForecastResponseDto, ForecastResponseDto, ForecastDebugResponseDto,
)
from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import FORECAST_SPEC
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC


def recognition_payload(code, period, view, *, stamp=None):
    stamp = stamp if stamp is not None else "2023-01-03" + ("" if period == "day" else "T15:00:00+08:00")
    raw = dict(
        tsCode=code, period=period, algorithmVersion="xxm-direction-v0.5-r4.1", specHash=MAIN_SPEC.spec_hash,
        source=dict(kind="daily_factor" if period == "day" else "minute_gold", inputId="literal-one-bar",
                    startTime=stamp, computedThrough=stamp, initialHistoryIncomplete=True,
                    indicatorVersion=None if period == "day" else 1),
        points=[dict(time=stamp, close=100, dif=0, dea=0, hist=0, ordinaryState="NONE",
                     ordinaryDirection=None, activeReference=None, activeStructureId=None)],
        events=[], structures=[], meta=dict(count=1, responseStart=stamp, responseEnd=stamp),
        dataStatus=dict(status="READY", message=None, asOf=stamp),
    )
    if view == "internal":
        return raw
    raw["source"].pop("inputId")
    raw.pop("structures")
    raw["points"][0].pop("activeReference")
    raw["points"][0].pop("activeStructureId")
    if view == "debug":
        raw["debug"] = dict(sourceInputId="literal-one-bar",
                            points=[dict(time=stamp, activeReference=None, activeStructureId=None)],
                            events=[], structures=[])
    return raw


def forecast_payload(code, period, view, *, stamp=None):
    stamp = stamp if stamp is not None else "2023-01-03" + ("" if period == "day" else "T15:00:00+08:00")
    # The zero bar cannot start a colored wave, so a next-bar solve is absent.
    facts = dict(
        tsCode=code, period=period, forecastVersion="xxm-key-point-forecast-v0.7-r4.1",
        forecastSpecHash=FORECAST_SPEC.spec_hash, detectorSpecHash=MAIN_SPEC.spec_hash,
        computedThrough=stamp, requestedAsOf=None, mode="LATEST", dataStatus="READY",
        ordinaryState="NONE", direction=None, targetEndpoint=None, barsAhead=None,
        status="NO_CANDIDATE", reasonCode="ZERO_WAVE",
    )
    details = dict(
        sourceInputId="literal-one-bar", calendarInputId=None,
        precisionPolicy="rounded3_guarded" if period == "day" else "full_float",
        references=dict(nearest=None, farther=None), selectedReference=None,
        nearestDecision=dict(status="NOT_EVALUATED", reason=None), farEvaluated=False,
        conditions=[], precisionRanges=[], structureFollowConditions=[],
    )
    identity = json.dumps(dict(facts, **details), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    raw = dict(facts, forecastId=hashlib.sha256(identity.encode()).hexdigest(),
               display=dict(statusLabel="暂无可用条件", targetText="下一根完成收盘条件尚未确定",
                            conditionsText="当前尚无有效红绿柱段，下一根不足以形成钝化。", asOfText="截至已完成收盘"),
               applicabilityText="仅用于下一根完成收盘条件核对", invalidationText="新完成收盘后重新计算",
               refreshAfterMs=60000)
    if view == "internal":
        raw.update(details)
    elif view == "debug":
        raw["debug"] = details
    return raw


CASES = (
    (InternalXxmResponseDto, recognition_payload, "internal"),
    (XxmResponseDto, recognition_payload, "public"),
    (XxmDebugResponseDto, recognition_payload, "debug"),
    (InternalForecastResponseDto, forecast_payload, "internal"),
    (ForecastResponseDto, forecast_payload, "public"),
    (ForecastDebugResponseDto, forecast_payload, "debug"),
)


@pytest.mark.parametrize("model,payload,view", CASES)
@pytest.mark.parametrize("period", ["day", "m30", "m60", "m90", "m120"])
@pytest.mark.parametrize("code", ["000001.SH", "399001.SZ", "899050.BJ", "000680.SH"])
def test_complete_dtos_accept_canonical_format_and_five_periods(model, payload, view, period, code):
    # BJ and a non-product code deliberately prove that DTOs check format only.
    raw = payload(code, period, view)
    original = deepcopy(raw)
    parsed = model.model_validate(raw)
    assert parsed.tsCode == code and parsed.period == period
    assert raw == original
    if payload is recognition_payload:
        assert parsed.meta.count == 1 and parsed.points[0].ordinaryState == "NONE"
    else:
        assert parsed.status == "NO_CANDIDATE" and parsed.reasonCode == "ZERO_WAVE"


@pytest.mark.parametrize("model,payload,view", CASES)
@pytest.mark.parametrize("code", [None, 1, True, b"000001.SH", " 000001.SH", "000001.SH ",
                                    "000001.sh", "000001SH", "00001.SH", "0000001.SH",
                                    "000001.HK", "０００００１.SH", "000001.SH\n"])
def test_complete_dtos_reject_code_coercion_or_normalization(model, payload, view, code):
    # First establish all other facts are valid, then alter only the code.
    raw = payload("399001.SZ", "m30", view)
    assert model.model_validate(raw).tsCode == "399001.SZ"
    raw["tsCode"] = code
    with pytest.raises(ValidationError) as rejected:
        model.model_validate(raw)
    assert any(issue["loc"] == ("tsCode",) for issue in rejected.value.errors())


@pytest.mark.parametrize("model,payload,view", CASES)
@pytest.mark.parametrize("period", ["m15", "m5", "week", "30", 30, None])
def test_dto_expansion_does_not_admit_other_periods(model, payload, view, period):
    raw = payload("399001.SZ", "m30", view)
    assert model.model_validate(raw).period == "m30"
    raw["period"] = period
    with pytest.raises(ValidationError) as rejected:
        model.model_validate(raw)
    assert any(issue["loc"] == ("period",) for issue in rejected.value.errors())


@pytest.mark.parametrize("model,payload,view", CASES)
@pytest.mark.parametrize("stamp", ["2023-01-03", "2023-01-03T10:00:00", "2023-01-03T10:00:00+00:00"])
def test_m30_dtos_keep_minute_timezone_validation(model, payload, view, stamp):
    assert model.model_validate(payload("399001.SZ", "m30", view)).period == "m30"
    # All time fields agree, and forecast identity is signed over these facts;
    # a mismatched copy/hash cannot mask the missing +08:00 validation.
    with pytest.raises(ValidationError):
        model.model_validate(payload("399001.SZ", "m30", view, stamp=stamp))
