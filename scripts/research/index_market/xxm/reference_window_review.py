"""Raw completed-colour windows and local turns; not the r4 reference policy."""
from src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import LocalExtremaScanner, number

def sign(value) -> int:
    x = number(value)
    return 1 if x > 0 else -1 if x < 0 else 0


def build_references(rows: list[dict]) -> dict:
    """Use only supplied prefix. Freeze each price window at its first opposite."""
    if not rows:
        raise ValueError("Empty prefix")
    phases, assignments, turns = [], [], []
    scanner = LocalExtremaScanner()
    for index, row in enumerate(rows):
        if number(row["close"]) <= 0:
            raise ValueError("Nonpositive close")
        colour = sign(row["macd"])
        if colour and (not phases or phases[-1]["sign"] != colour):
            if phases:
                phases[-1]["end_exclusive"] = index
            phases.append(dict(id=len(phases), sign=colour, start=index,
                               end_exclusive=None, actual_bars=0,
                               left_censored=not phases))
        if colour:
            phases[-1]["actual_bars"] += 1
        assignments.append(phases[-1]["id"] if phases else None)
        point = scanner.step(row["trade_time"], row["macd_dif"])
        if point:
            turns.append(point.record())

    references, censored = [], []
    for point in turns:
        first, last = point["first_index"], point["last_index"]
        phase_id = assignments[first]
        if phase_id is None:
            continue
        phase = phases[phase_id]
        expected = "MAX" if phase["sign"] > 0 else "MIN"
        if point["kind"] != expected:
            continue
        if phase["left_censored"]:
            censored.append(dict(point=point, reason="left_censored_phase"))
            continue
        end = phase["end_exclusive"]
        if end is None:
            continue  # Current phase cannot be its own historical reference.
        if last >= end:
            censored.append(dict(point=point, reason="plateau_crosses_colour_boundary"))
            continue
        direction = "TOP" if phase["sign"] > 0 else "BOTTOM"
        price_index = (max if direction == "TOP" else min)(
            range(first, end), key=lambda i: number(rows[i]["close"]))
        references.append(dict(
            id=f"{direction}:{point['first_at']}", direction=direction,
            phase_id=phase_id, dif=point["value"],
            peak_first=point["first_at"], peak_last=point["last_at"],
            confirmed_at=point["confirmed_at"], first_index=first,
            window_start=rows[first]["trade_time"],
            window_last=rows[end - 1]["trade_time"],
            first_opposite=rows[end]["trade_time"],
            price=rows[price_index]["close"], price_at=rows[price_index]["trade_time"],
        ))
    return dict(phases=phases, assignments=assignments, references=references,
                censored=censored, raw_turns=turns)
