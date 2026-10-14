"""Separate completed-history membership from active and confirmed references.

Bounded research trace of existing candidates. No selection, event, label or
trade implementation is changed by the membership diagnostic.
"""
import hashlib
import json
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
START, END = "2025-09-18", "2025-10-27"
DEFS = ROOT / "october_reference_membership_definitions_20261012.json"
KEYS = ("event", "state", "event_direction", "event_route", "event_ref_start")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(rows):
    history = {1: [], -1: []}
    wave = None
    result = []
    for row in rows:
        sign = (row["hist"] > 0) - (row["hist"] < 0)
        if wave is None or sign != wave["sign"]:
            if wave and wave["sign"]:
                history[wave["sign"]].append(dict(wave))
            wave = dict(start=row["time"], sign=sign, count=0,
                        price=row["close"], dif=row["dif"])
        wave["count"] += 1
        if sign * (row["close"] - wave["price"]) > 0:
            wave["price"] = row["close"]
        if sign * (row["dif"] - wave["dif"]) > 0:
            wave["dif"] = row["dif"]
        result.append(dict(time=row["time"], wave=dict(wave),
                           history={d: [dict(v) for v in history[d]] for d in (1, -1)}))
    return result


def opportunity(snapshot, reference_start, direction, window):
    completed = snapshot["history"][direction]
    wave = snapshot["wave"]
    pool = completed[-window:]
    match = next((v for v in completed if v["start"] == reference_start), None)
    membership = any(v["start"] == reference_start for v in pool)
    comparable = wave["sign"] == direction and wave["count"] >= 2 and bool(completed)
    # These checks describe a possible new selection only. They must not clear
    # an active locked reference or retract a past confirmed structure.
    nearest_price = direction * (wave["price"]-completed[-1]["price"]) > 0 if comparable else None
    pair_price = direction * (wave["price"]-match["price"]) > 0 if comparable and match else None
    pair_dif = direction * (wave["dif"]-match["dif"]) < 0 if comparable and match else None
    return dict(in_last_completed_window=membership,
                completed_rank_from_latest=(len(completed)-next(i for i,v in enumerate(completed) if v["start"]==reference_start)) if match else None,
                comparable_now=comparable, nearest_price_ok=nearest_price,
                pair_price_ok=pair_price, pair_dif_ok=pair_dif,
                qualifies_for_new_selection=bool(comparable and membership and nearest_price and pair_price and pair_dif),
                pool=[dict(v) for v in pool])


def monitor(rows, gate, reference_policy="nearest_qualifying"):
    output = replay(rows, gate, diagnostics=True, reference_policy=reference_policy)
    inv = inventory(rows)
    records = []
    for i, event in enumerate(output):
        if event["event"] != "STRUCTURE" or event["time"][:10] < START:
            continue
        direction, ref_start, dif = event["event_direction"], event["event_ref_start"], event["event_ref_dif"]
        raw_cross = next((r["time"] for r in rows[i+1:] if direction*(r["dif"]-dif)>0), None)
        trace = {}
        windows = {}
        for n in (2, 3):
            gone = next((j for j in range(i,len(inv)) if not opportunity(inv[j],ref_start,direction,n)["in_last_completed_window"]), None)
            first_gone = inv[gone]["time"] if gone is not None else None
            windows[str(n)] = dict(first_out_of_window=first_gone,
                                   already_out_at_confirmation=gone == i)
            targets = {event["time"]}
            targets.update(r["time"] for r in rows if r["time"][:10] in {"2025-10-16","2025-10-24",END} and r["time"] >= event["time"])
            if first_gone:
                targets.add(first_gone)
            if raw_cross:
                targets.add(raw_cross)
            for j,snap in enumerate(inv):
                if snap["time"] in targets:
                    trace.setdefault(snap["time"], dict(raw_dif=rows[j]["dif"],
                        baseline_event=output[j]["event"], baseline_state=output[j]["state"],
                        current_wave=inv[j]["wave"], baseline_active_reference=output[j]["reference_refresh"]["active_reference"], windows={}))
                    trace[snap["time"]]["windows"][str(n)] = opportunity(snap,ref_start,direction,n)
        records.append(dict(confirmed_at=event["time"], direction=direction,
                            original_reference_start=ref_start, original_reference_dif=dif,
                            first_raw_cross=raw_cross, membership_windows=windows,
                            trace=trace))
    return output, inv, records


def check_prefixes(rows, gate, policy, baseline, inv, records):
    targets=set(t for r in records for t in r["trace"])
    targets.update(r["time"] for r in baseline if START<=r["time"][:10]<=END and r["event"]!="NONE")
    for time in sorted(targets):
        ix=next(i for i,r in enumerate(rows) if r["time"]==time)
        b2, inv2, partial=monitor(rows[:ix+1],gate,policy)
        assert inv2[-1]==inv[ix]
        assert all(b2[-1][k]==baseline[ix][k] for k in KEYS)
        for record in partial:
            full=next(r for r in records if r["confirmed_at"]==record["confirmed_at"])
            expected_cross=full["first_raw_cross"]
            assert record["first_raw_cross"]==(expected_cross if expected_cross and expected_cross<=time else None)
            for n in ("2","3"):
                expected=full["membership_windows"][n]["first_out_of_window"]
                assert record["membership_windows"][n]["first_out_of_window"]==(expected if expected and expected<=time else None)
            if time in record["trace"]:
                assert record["trace"][time]==full["trace"][time]
    return len(targets)


def episode_trace(inputs, gate, policy):
    anchor = "2025-09-18 15:00:00"
    profiles = {}
    for period, rows in inputs.items():
        baseline, inv, records = monitor(rows, gate, policy)
        original = next(r for r in records if r["confirmed_at"][:10] == START)
        profiles[period] = dict(rows=rows, baseline=baseline, inv=inv,
                                original=original)
    times = sorted({r["time"] for rows in inputs.values() for r in rows
                    if r["time"] >= anchor})
    indices = {p: -1 for p in inputs}
    ever_cancel = {p: False for p in inputs}
    latest_top = {p: None for p in inputs}
    top_events = {p: [] for p in inputs}
    trace = []
    for time in times:
        states, membership, crosses = {}, {}, {}
        for p, profile in profiles.items():
            rows, events = profile["rows"], profile["baseline"]
            while indices[p]+1 < len(rows) and rows[indices[p]+1]["time"] <= time:
                indices[p] += 1
                e = events[indices[p]]
                if e["time"] >= anchor and e["event_direction"] == 1 and e["event"] in {"DULL", "STRUCTURE", "CANCEL"}:
                    latest_top[p] = e["event"]
                    ever_cancel[p] = ever_cancel[p] or e["event"] == "CANCEL"
                    top_events[p].append({k: e[k] for k in ("time", "event", "event_route", "event_ref_start", "event_ref_dif")})
            assert indices[p] >= 0
            states[p] = events[indices[p]]["state"]
            original = profile["original"]
            membership[p] = not opportunity(profile["inv"][indices[p]], original["original_reference_start"], 1, 2)["in_last_completed_window"]
            cross = original["first_raw_cross"]
            crosses[p] = bool(cross and cross <= time)
        trace.append(dict(time=time, latest_bar={p: v["rows"][indices[p]]["time"] for p,v in profiles.items()},
            joint_predicates=dict(current_none=all(s == "NONE" for s in states.values()),
                september_ref_out_window2=all(membership.values()),
                september_ref_crossed=all(crosses.values()),
                ever_top_cancel=all(ever_cancel.values()),
                latest_top_event_cancel=all(e == "CANCEL" for e in latest_top.values())),
            current_states=states, latest_top_events=dict(latest_top)))
    first = {k: next((r["time"] for r in trace if r["joint_predicates"][k]), None)
             for k in trace[0]["joint_predicates"]}
    checkpoints = {date: next(r for r in reversed(trace) if r["time"][:10] <= date)
                   for date in ("2025-10-16", "2025-10-24", "2025-10-27")
                   if trace[0]["time"][:10] <= date}
    return dict(first_joint_true=first, checkpoints=checkpoints,
                top_events=top_events, trace=trace)


def source_context():
    terms = {"20251016": ["90分钟和120分钟", "全部钝化消失"],
             "20251024": ["这个消失是结构消失", "反复的红角线绿角线", "结构形成的纠错标准", "90分钟只形成过", "9月18号到现在"],
             "20251027": ["近期没有结构", "这个消失是结构消失"]}
    result = {}
    for date, markers in terms.items():
        path = ROOT / "sources" / f"{date}_vidiq_transcript.json"
        text = json.loads(path.read_text())["response"]["transcription"]
        positions = {term: text.find(term) for term in markers}
        assert all(pos >= 0 for pos in positions.values())
        result[date] = dict(file=str(path.relative_to(ROOT)), sha256=sha(path),
                            zero_based_character_offsets=positions,
                            locator_is_not_video_timestamp=True)
    return result


def main():
    previous = json.loads((ROOT / "correction_lifecycle_20261012.json").read_text())
    out = dict(definitions_sha256=sha(DEFS), status="RETROSPECTIVE_MEMBERSHIP_DIAGNOSTIC_NOT_SOFTWARE_VALIDITY",
               candidate_sha256=sha(ROOT/"active_reference_candidate.py"), scope=dict(start=START,end=END),
               periods={}, prefix_checks=0, new_software_labels=0,
               source_context=source_context())
    inputs = {}
    for period,name in ((90,"90_20250603_20260113.csv"),(120,"120_20250401_20251111.csv")):
        rows=[r for r in read_rows(name) if r["time"][:10]<=END]
        inputs[str(period)] = rows
        assert sha(ROOT/"inputs"/name)==previous["periods"][str(period)]["input_sha256"]
        variants=[]
        for gate in (.75,1.,1.2):
            baseline, inv, records = monitor(rows,gate)
            old = next(v for v in previous["periods"][str(period)]["variants"] if v["gate_pct"]==gate)["confirmed_reference_records"]
            assert [(r["confirmed_at"],r["original_reference_start"],r["original_reference_dif"],r["first_raw_cross"]) for r in records] == [(r["confirmed_at"],r["reference_start"],r["reference_dif"],r["first_strict_cross"]) for r in old]
            out["prefix_checks"]+=check_prefixes(rows,gate,"nearest_qualifying",baseline,inv,records)
            strong_output,strong_inv,strong_records=monitor(rows,gate,"strongest_eligible")
            out["prefix_checks"]+=check_prefixes(rows,gate,"strongest_eligible",strong_output,strong_inv,strong_records)
            strongest={n:replay(rows,gate,reference_policy="strongest_eligible",max_refs=n) for n in (2,3)}
            parity=[rows[i]["time"] for i,b in enumerate(baseline) if START<=b["time"][:10]<=END and any(b[k]!=strongest[2][i][k] for k in KEYS)]
            diff=[dict(time=rows[i]["time"], window2=strongest[2][i],window3=strongest[3][i]) for i in range(len(rows)) if START<=rows[i]["time"][:10]<=END and any(strongest[2][i][k]!=strongest[3][i][k] for k in KEYS)]
            variants.append(dict(gate_pct=gate,records=records,strongest2_records=strong_records,nearest2_vs_strongest2_differences=parity,
                                 strongest2_vs_strongest3_differences=diff))
        assert all(v["records"]==variants[0]["records"] for v in variants)
        assert all(v["strongest2_records"]==variants[0]["strongest2_records"] for v in variants)
        out["periods"][str(period)]=dict(input=name,input_sha256=sha(ROOT/"inputs"/name),variants=variants)
    out["episode_checkpoint_profiles"] = []
    out["episode_prefix_checks"] = 0
    for gate in (.75, 1., 1.2):
        for policy in ("nearest_qualifying", "strongest_eligible"):
            episode = episode_trace(inputs, gate, policy)
            for date, checkpoint in episode["checkpoints"].items():
                endpoint = checkpoint["time"]
                partial = episode_trace({p: [r for r in rows if r["time"] <= endpoint]
                                         for p, rows in inputs.items()}, gate, policy)
                assert partial["trace"][-1] == checkpoint
                for k, first in episode["first_joint_true"].items():
                    assert partial["first_joint_true"][k] == (first if first and first <= endpoint else None)
                out["episode_prefix_checks"] += 1
            out["episode_checkpoint_profiles"].append(dict(gate_pct=gate, policy=policy, **episode))
    extended_inputs = {str(p): [r for r in read_rows(name) if r["time"][:10] <= "2025-11-11"]
                       for p,name in ((90,"90_20250603_20260113.csv"), (120,"120_20250401_20251111.csv"))}
    out["followup_screen"] = []
    out["followup_prefix_checks"] = 0
    for gate in (.75, 1., 1.2):
        for policy in ("nearest_qualifying", "strongest_eligible"):
            extended = episode_trace(extended_inputs, gate, policy)
            differing = [r for r in extended["trace"] if r["time"][:10] > END and
                         r["joint_predicates"]["ever_top_cancel"] != r["joint_predicates"]["latest_top_event_cancel"]]
            changes = []
            previous = None
            for point in differing:
                signature = point["latest_top_events"]
                if signature != previous:
                    changes.append(point)
                    previous = signature
            for point in changes:
                endpoint = point["time"]
                partial = episode_trace({p: [r for r in rows if r["time"] <= endpoint]
                                         for p, rows in extended_inputs.items()}, gate, policy)
                assert partial["trace"][-1] == point
                out["followup_prefix_checks"] += 1
            out["followup_screen"].append(dict(gate_pct=gate, policy=policy,
                first_divergence=differing[0] if differing else None,
                divergent_state_changes=changes,
                top_events={p:[e for e in events if e["time"][:10] > END]
                            for p,events in extended["top_events"].items()}))
    (ROOT/"october_reference_membership_20261012.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(dict(prefix_checks=out["prefix_checks"],periods={p:dict(records=[{k:v for k,v in r.items() if k!="trace"} for r in item["variants"][1]["records"]],baseline_policy_difference_count=len(item["variants"][1]["nearest2_vs_strongest2_differences"]),window_difference_times=[r["time"] for r in item["variants"][1]["strongest2_vs_strongest3_differences"]]) for p,item in out["periods"].items()}),ensure_ascii=False))


if __name__ == "__main__":
    main()
