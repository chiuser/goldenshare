"""Offline bottom-DULL review only, next plan section 10 / LLD section 12.

Conditional initialization is explicit. Stops at the first STRUCTURE; does not
implement structure cancellation, full history, a production API, or source IO.
"""
from __future__ import annotations

from copy import deepcopy

from src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import number
from .near_first_review import quantize_dif
from .reference_window_review import inspect_prefix


def _validate_state(state: dict) -> None:
    if state.get("kind") not in ("NONE", "DULL", "STRUCTURE"):
        raise ValueError("Unknown state")
    if state.get("direction") not in ("TOP", "BOTTOM"):
        raise ValueError("Unknown direction")
    if not isinstance(state.get("as_of"), str) or not state["as_of"]:
        raise ValueError("State needs a completed time")
    if state["kind"] == "NONE":
        if state.get("reference") is not None or state.get("episode_id") is not None:
            raise ValueError("NONE cannot have an active reference")
    else:
        ref = state.get("reference")
        if not isinstance(ref, dict) or not ref.get("id") or not state.get("episode_id"):
            raise ValueError("Active state needs its original reference and episode")
        if ref.get("direction") != state["direction"]:
            raise ValueError("Reference direction differs")
        number(ref["qdif"])


def display_events(previous_state: dict, state: dict, events: list[dict]) -> dict:
    """Keep all internal events; omit only an exact same-bar DULL replacement."""
    _validate_state(previous_state)
    _validate_state(state)
    if previous_state["as_of"] >= state["as_of"]:
        raise ValueError("States must advance")
    for event in events:
        if event.get("kind") not in ("CANCEL", "DULL", "STRUCTURE"):
            raise ValueError("Unknown event")
        if event.get("time") != state["as_of"]:
            raise ValueError("Events must belong to the current completed candle")
        if event.get("direction") not in ("TOP", "BOTTOM"):
            raise ValueError("Unknown event direction")
    suppress = False
    if (previous_state["kind"] == state["kind"] == "DULL"
            and previous_state["direction"] == state["direction"]
            and len(events) == 2):
        cancel, start = events
        suppress = (
            cancel["kind"] == "CANCEL" and start["kind"] == "DULL"
            and cancel["direction"] == start["direction"] == state["direction"]
            and cancel.get("episode_id") == previous_state["episode_id"]
            and start.get("episode_id") == state["episode_id"]
            and cancel.get("reference_id") == previous_state["reference"]["id"]
            and start.get("reference_id") == state["reference"]["id"]
            and state["episode_id"] != previous_state["episode_id"]
            and state["reference"]["id"] != previous_state["reference"]["id"]
        )
    return dict(visible_events=[] if suppress else deepcopy(events),
                suppressed_events=deepcopy(events) if suppress else [])


def advance_bottom(rows: list[dict], previous_state: dict | None = None) -> dict:
    """Advance one completed prefix, holding the reference until strict failure.

    With no previous state, assume this candle may start a new round. No old
    model state or reference enters that conditional initial selection.
    """
    if len(rows) < 2:
        raise ValueError("Need the previous completed candle")
    last_time = None
    for row in rows:
        key = row.get("trade_time")
        if not isinstance(key, str) or not key or (last_time is not None and key <= last_time):
            raise ValueError("Duplicate or unordered input")
        if row.get("completed", True) is not True:
            raise ValueError("Only completed candles are supported")
        if number(row["close"]) <= 0:
            raise ValueError("Nonpositive close")
        number(row["macd_dif"])
        number(row["macd"])
        last_time = key
    before = deepcopy(previous_state) if previous_state is not None else dict(
        kind="NONE", direction="BOTTOM", reference=None, episode_id=None,
        as_of=rows[-2]["trade_time"],
    )
    _validate_state(before)
    if before["direction"] != "BOTTOM":
        raise ValueError("Only bottom calculation is implemented")
    if before["kind"] == "STRUCTURE":
        raise ValueError("Stop at first STRUCTURE; later correction is not implemented")
    if before["as_of"] != rows[-2]["trade_time"]:
        raise ValueError("State must be from the immediately previous candle")
    probe = inspect_prefix(rows, "BOTTOM")
    state = deepcopy(before)
    state["as_of"] = probe["time"]
    events = []

    def emit(kind: str, reason: str) -> None:
        events.append(dict(kind=kind, direction="BOTTOM", time=state["as_of"],
                           episode_id=state["episode_id"],
                           reference_id=state["reference"]["id"], reason=reason))

    current_qdif = number(probe["latest_qdif"])
    if state["kind"] == "DULL" and current_qdif < number(state["reference"]["qdif"]):
        emit("CANCEL", "current_quantized_DIF_strictly_below_original_valley")
        state.update(kind="NONE", reference=None, episode_id=None)
    if state["kind"] == "NONE":
        selected = probe["ranges"]["recent_two_phases"]["selected"]
        if selected is not None:
            state.update(kind="DULL", reference=deepcopy(selected),
                         episode_id=f"BOTTOM:{state['as_of']}:{selected['id']}")
            emit("DULL", "independent_current_prefix_conditions")
    if state["kind"] == "DULL" and current_qdif > quantize_dif(rows[-2]["macd_dif"]):
        emit("STRUCTURE", "quantized_DIF_turned_up_from_previous_completed_candle")
        state["kind"] = "STRUCTURE"
    drawn = display_events(before, state, events)
    return dict(previous_state=before, state=state, probe=probe,
                internal_events=events, **drawn)
