"""One completed bar only, with an explicit nearest-reference decision."""
from copy import deepcopy
import math

from .calculator import XxmCalculator
from .forecast_detector import clone, next_bar_evaluations
from .forecast_entry import solve_first_dull
from .forecast_next import solve_active_reference
from .projection import ProjectionState
from .types import ForecastKernelResult, ForecastPrecheck, ReferenceForecast, XxmBar


def _already_broken(c, reference):
    try:
        difference = c.wave.dif - reference.dif
        valid = math.isfinite(difference)
    except (OverflowError, TypeError) as exc:
        raise ValueError("Non-finite reference comparison") from exc
    if not valid:
        raise ValueError("Non-finite reference comparison")
    return c._reference_was_broken(c.wave, reference)


def precheck_next_bar(c, check):
    """Inspect the real progress without sources or hypothetical closes."""
    check()
    if type(c) is not XxmCalculator:
        raise ValueError("Forecast requires the formal r4 calculator")
    snapshot = c.snapshot()
    clone(c)
    wave = c.wave
    pool = list(reversed(c.history[wave.sign])) if wave is not None else []
    if len(pool) > c.spec.max_refs:
        raise ValueError("Forecast reference pool exceeds the formal limit")
    references = {"nearest": pool[0].reference() if pool else None,
                  "farther": pool[1].reference() if len(pool) == 2 else None}
    direction = ("TOP" if wave.sign == 1 else "BOTTOM") if wave is not None else None
    active_role = None
    if c.reference is not None:
        for index, reference in enumerate(pool):
            if reference == c.reference:
                active_role = "NEAR" if index == 0 else "FAR"
                break
        if active_role is None:
            raise ValueError("Active reference is absent from the real pool")
    decision = {"status": "NOT_EVALUATED", "reason": None}
    stop = None
    if wave is None:
        stop = "ZERO_WAVE"
    elif c.state == "NONE":
        if not pool:
            decision = {"status": "UNAVAILABLE", "reason": "没有可比较的近参照。"}
            stop = "NO_REFERENCE"
        elif wave.count + 1 < c.spec.min_bars:
            stop = "NO_ENTRY_RANGE"
        elif _already_broken(c, pool[0]):
            decision = {"status": "UNAVAILABLE", "reason": "近参照已被本轮DIF严格突破。"}
            # Do not examine A eligibility while an unbroken B can still work.
            if len(pool) == 1 or _already_broken(c, pool[1]):
                stop = "NO_ENTRY_RANGE"
    elif c.state not in ("DULL", "STRUCTURE") or active_role is None:
        raise ValueError("Invalid forecast state")
    result = ForecastPrecheck(deepcopy(snapshot), direction, deepcopy(references), active_role,
                              deepcopy(decision), stop)
    check()
    return result


def _result(prepared, *, status, reason, endpoint=None, selected=None, nearest=None,
            far=False, solved=None):
    conditions = deepcopy(solved.conditions) if solved is not None else ()
    precision = tuple({"priceRange": interval.json(), "reason": "ROUNDING_BOUNDARY"}
                      for interval in solved.precision_ranges) if solved is not None else ()
    return ForecastKernelResult(status, reason, endpoint, 1 if endpoint is not None else None,
                                deepcopy(prepared.references), selected,
                                deepcopy(nearest or prepared.nearest_decision), far,
                                conditions, deepcopy(precision))


def _resolved(prepared, solved, *, endpoint, role, nearest, far, relationships_only=False):
    if type(solved) is not ReferenceForecast:
        raise ValueError("Invalid single-reference result")
    has_range = bool(solved.relationship_ranges) if relationships_only else bool(solved.conditions)
    pending = bool(solved.relationship_precision_ranges) if relationships_only else bool(solved.precision_ranges)
    if has_range:
        return _result(prepared, status="READY", reason="ROUNDING_BOUNDARY" if solved.precision_ranges else None,
                       endpoint=endpoint, selected=role, nearest=nearest, far=far, solved=solved)
    if pending:
        return _result(prepared, status="PRECISION_PENDING", reason="ROUNDING_BOUNDARY", endpoint=endpoint,
                       selected=role, nearest=nearest, far=far, solved=solved)
    return _result(prepared, status="NO_CANDIDATE", reason="NO_ENTRY_RANGE", endpoint=endpoint,
                   selected=role, nearest=nearest, far=far)


def forecast(c, projection, endpoint, check, *, prepared):
    """Return only the internal next-bar result; HTTP assembly is a later step."""
    check()
    if type(prepared) is not ForecastPrecheck or prepared != precheck_next_bar(c, check):
        raise ValueError("Forecast preparation differs from the real progress")
    if endpoint is not None and type(endpoint) is not str:
        raise ValueError("Forecast takes a single endpoint, never a sequence")
    if prepared.stop_reason is not None:
        result = _result(prepared, status="NO_CANDIDATE", reason=prepared.stop_reason)
        check()
        return result
    if type(projection) is not ProjectionState:
        raise ValueError("Invalid original EMA projection")
    try:
        valid = all(type(value) in (int, float) and math.isfinite(value)
                    for value in (projection.e12, projection.e26, projection.dea))
    except OverflowError as exc:
        raise ValueError("Non-finite original EMA projection") from exc
    if not valid:
        raise ValueError("Invalid original EMA projection")
    XxmBar(endpoint, 1., 0., 0., 0.).validate(c.period)
    if c.previous is None or endpoint <= c.previous.time:
        raise ValueError("Forecast endpoint must follow the real prefix")
    pool = list(reversed(c.history[c.wave.sign]))
    solver = solve_first_dull if c.state == "NONE" else solve_active_reference
    with next_bar_evaluations():
        if c.state == "STRUCTURE" or prepared.active_role == "FAR":
            role = prepared.active_role
            nearest = {"status": "NOT_EVALUATED", "reason": "沿已选原参照继续考核，不重新选择近远。"}
            solved = solver(c, projection, endpoint, c.reference, role, check)
            result = _resolved(prepared, solved, endpoint=endpoint, role=role,
                               nearest=nearest, far=role == "FAR")
        else:
            near, solved, role = pool[0], None, None
            if _already_broken(c, near):
                nearest = {"status": "UNAVAILABLE", "reason": "近参照已被本轮DIF严格突破。"}
            else:
                role = "NEAR"
                solved = solver(c, projection, endpoint, near, role, check)
                if solved.relationship_ranges:
                    nearest = {"status": "HAS_RANGE", "reason": "近参照有有效关系范围，远参照未计算。"}
                elif solved.relationship_precision_ranges:
                    nearest = {"status": "UNCERTAIN", "reason": "近参照关系仍有临界未决范围，远参照未计算。"}
                else:
                    nearest = {"status": "NO_RANGE", "reason": "近参照没有有效的首次或延续范围。"}
            if solved is not None and (solved.relationship_ranges or solved.relationship_precision_ranges):
                result = _resolved(prepared, solved, endpoint=endpoint, role=role, nearest=nearest,
                                   far=False, relationships_only=True)
            elif len(pool) != 2 or _already_broken(c, pool[1]):
                nearest["reason"] += "远参照不存在或已被本轮DIF突破，没有救援范围。"
                result = _result(prepared, status="NO_CANDIDATE", reason="NO_ENTRY_RANGE",
                                 endpoint=endpoint, selected=role, nearest=nearest)
            else:
                check()
                far = solver(c, projection, endpoint, pool[1], "FAR", check)
                if not far.relationship_ranges and not far.relationship_precision_ranges:
                    nearest["reason"] += "远参照也没有首次或救援范围。"
                result = _resolved(prepared, far, endpoint=endpoint, role="FAR", nearest=nearest,
                                   far=True, relationships_only=True)
    check()
    return result
