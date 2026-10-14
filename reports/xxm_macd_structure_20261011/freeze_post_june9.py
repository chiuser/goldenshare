"""Freeze historical numeric predictions before reading follow-up author text.

No algorithm tuning, labels, trading, network, DB or Lake access. Every metric
is a research proxy, not a recovered author formula or software observation.
"""
import csv
import hashlib
import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
DEFINITIONS = ROOT / "post_june9_definitions_20261012.json"
OUT = ROOT / "post_june9_predictions_20261012.json"
KEYS = ("event", "state", "event_direction", "event_route", "event_ref_start")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(wave, previous=None):
    rows = wave["rows"]
    closes, difs, hist = ([r[k] for r in rows] for k in ("close", "dif", "hist"))
    drop = 100 * (closes[0] - min(closes)) / closes[0]
    out = dict(start=rows[0]["time"], end=rows[-1]["time"], sign=wave["sign"],
               bars=len(rows), closed=wave["closed"], min_close=min(closes), max_close=max(closes),
               min_dif=min(difs), max_dif=max(difs), first_close=closes[0], last_close=closes[-1],
               drawdown_pct=drop, drawdown_per_interval=drop/(len(rows)-1) if len(rows)>1 else None)
    if wave["sign"] == 1:
        out.update(red_peak=max(hist), red_sum=sum(hist))
        if previous and previous["sign"] == -1:
            old = previous["rows"]
            old_min = min(r["close"] for r in old)
            out.update(rebound_pct=100*(max(closes)-old_min)/old_min,
                       dif_recovery=max(difs)-min(r["dif"] for r in old))
    return out


def waves(rows):
    result = []
    for r in rows:
        sign = (r["hist"] > 0) - (r["hist"] < 0)
        if not result or sign != result[-1]["sign"]:
            if result:
                result[-1]["closed"] = True
            result.append(dict(sign=sign, rows=[], closed=False))
        result[-1]["rows"].append(r)
    return result


def main():
    defs = json.loads(DEFINITIONS.read_text())
    start, end, cutoff = defs["start"], defs["end"], defs["lecture_cutoff"]
    source_paths = {60: ROOT/"inputs/60_20250603_20261009.csv",
                    90: ROOT/"discrimination_screen_20261012/derived_90.csv",
                    120: ROOT/"discrimination_screen_20261012/derived_120.csv"}
    out = dict(status=defs["status"], scope=dict(start=start, end=end, cutoff=cutoff),
               definitions_sha256=sha(DEFINITIONS), candidate_sha256=sha(ROOT/"active_reference_candidate.py"),
               software_labels_added=0, series={}, prefix_checks=0)
    series = {}
    for freq, path in source_paths.items():
        if freq == 60:
            rows = read_rows(path.name)
        else:
            with path.open(newline="") as h:
                rows = [dict(time=r["time"], **{k:float(r[k]) for k in ("close", "dif", "hist")})
                        for r in csv.DictReader(h)]
        rows = [r for r in rows if r["time"][:10] <= end]
        series[freq] = rows
        w = waves(rows)
        anchor = next(i for i, v in enumerate(w) if any(r["time"] == cutoff+" 15:00:00" for r in v["rows"]))
        red = next((i for i in range(anchor+1, len(w)) if w[i]["sign"]==1), None)
        green = next((i for i in range(red+1, len(w)) if w[i]["sign"]==-1), None) if red is not None else None
        baseline = replay(rows, 1., diagnostics=True)
        indexes = [i for i,r in enumerate(rows) if start <= r["time"][:10] <= end]
        events = [baseline[i] for i in indexes if baseline[i]["event"] != "NONE"]
        variants = []
        first_baseline_bottom = next((r["time"] for r in events if r["event"]=="STRUCTURE" and r["event_direction"]==-1), None)
        for gate in (.75, 1., 1.2):
            for policy in ("locked", "both_before", "dull_before", "both_after"):
                v = replay(rows, gate, active_policy=policy)
                changes = [rows[i]["time"] for i in indexes if any(v[i][k]!=baseline[i][k] for k in KEYS)]
                probes = [i for i in indexes if v[i]["event"] != "NONE"]
                if red is not None:
                    probes.append(next(i for i,r in enumerate(rows) if r["time"]==w[red]["rows"][0]["time"]))
                for i in set(probes):
                    last = replay(rows[:i+1], gate, active_policy=policy)[-1]
                    assert all(last[k]==v[i][k] for k in KEYS)
                    out["prefix_checks"] += 1
                first_bottom = next((v[i]["time"] for i in indexes if v[i]["event"]=="STRUCTURE" and v[i]["event_direction"]==-1), None)
                variants.append(dict(gate_pct=gate, active_policy=policy,
                                     different_times=changes, first_bottom_structure=first_bottom))
        out["series"][str(freq)] = dict(
            path=str(path.relative_to(REPO)), source_sha256=sha(path),
            origin="SAVED_DG" if freq==60 else "DERIVED_NOT_SOFTWARE_HISTORY",
            anchor_wave=summarize(w[anchor]),
            first_red=summarize(w[red], w[red-1]) if red is not None else None,
            next_green=summarize(w[green]) if green is not None else None,
            observed_waves=[summarize(v, w[i-1] if i else None) for i,v in enumerate(w) if i>=anchor],
            baseline_events=events, baseline_first_bottom_structure=first_baseline_bottom, variants=variants)
    fixture = REPO/"tests/fixtures/quote_trend_channel/000001_sh_daily_input.json"
    expected_path = REPO/"tests/fixtures/quote_trend_channel/000001_sh_daily_expected_v1.json"
    payload, expected = json.loads(fixture.read_text()), json.loads(expected_path.read_text())
    assert sha(fixture)==expected["input_file_sha256"]=="ed585326d64fae260f14e7ec53b885037db31609726ed38cb20c1cbe772e42ad"
    calculator_path = REPO/"src/biz/services/quote_trend_channel_calculator.py"
    spec = importlib.util.spec_from_file_location("research_trend_calculator", calculator_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    input_rows = [SimpleNamespace(trade_date=date.fromisoformat(r["trade_date"]),
                                 updated_at=datetime(2026,8,7,tzinfo=timezone.utc),
                                 **{k:Decimal(r[k]) for k in ("open","high","low","close")})
                  for r in payload["rows"] if r["trade_date"] <= end]
    calculated = module.TrendChannelCalculator().calculate(input_rows)
    expected_map = {r["trade_date"]:r for r in expected["rows"]}
    overlap = {r["time"][:10]:r["close"] for r in series[60] if r["time"][11:16]=="15:00"}
    trend_rows, errors, close_errors, close_comparison = [], [], [], []
    for r in calculated:
        d = r.trade_date.isoformat()
        ref = expected_map[d]
        for key in ("short_channel", "long_channel"):
            band = getattr(r, key)
            assert band.state==ref[key]["state"] and band.position==ref[key]["position"]
            errors.extend(abs(getattr(band,k)-float(ref[key][k])) for k in ("upper_raw","lower_raw"))
        if "2026-06-05" <= d <= end:
            close_errors.append(abs(float(r.close)-overlap[d]))
            positions = {}
            for key in ("short_channel", "long_channel"):
                band = getattr(r,key)
                alternate = "ABOVE" if overlap[d]>band.upper_raw else "BELOW" if overlap[d]<band.lower_raw else "INSIDE"
                positions[key] = alternate == band.position
            close_comparison.append(dict(date=d, fixture_close=float(r.close), minute_close=overlap[d],
                                         difference=float(r.close)-overlap[d],
                                         same_position_with_fixed_bands=positions))
            trend_rows.append(dict(date=d,close=float(r.close), **{
                key:dict(upper=getattr(r,key).upper_raw, lower=getattr(r,key).lower_raw,
                         position=getattr(r,key).position, state=getattr(r,key).state)
                for key in ("short_channel","long_channel")}))
    routes={}
    for key in ("short_channel", "long_channel"):
        first_upper=next((r for r in trend_rows if r["date"]>=start and r[key]["position"]=="ABOVE"),None)
        first_lower=next((r for r in trend_rows if r["date"]>=start and r["close"]>r[key]["lower"]),None)
        routes[key]=dict(first_upper_break=first_upper, first_lower_entry=first_lower)
    out["trend"] = dict(source=str(fixture.relative_to(REPO)), source_sha256=sha(fixture),
                        metadata=payload["source"], calculator_sha256=sha(calculator_path),
                        expected_sha256=sha(expected_path), expected_max_boundary_error=max(errors),
                        june_close_overlap_max_error=max(close_errors), close_comparison=close_comparison,
                        close_overlap_status="DIFFERENT_SAVED_INPUTS_NO_ASSUMED_PRECISION_CORRECTION",
                        rows=trend_rows, routes=routes,
                        limitations="Fixed historical serving fixture, not live DB or original software trend values")
    assert out["trend"]["expected_max_boundary_error"] < 1e-8
    assert all(all(v["same_position_with_fixed_bands"].values()) for v in close_comparison)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"prefix_checks":out["prefix_checks"],
        "periods":{k:{"first_red":v["first_red"]["start"] if v["first_red"] else None,
                      "next_green":v["next_green"]["start"] if v["next_green"] else None,
                      "first_bottom":v["baseline_first_bottom_structure"],
                      "variant_differences":sum(bool(a["different_times"]) for a in v["variants"])} for k,v in out["series"].items()},
        "trend_routes":{k:{a:(r["date"] if r else None) for a,r in v.items()} for k,v in routes.items()},
        "trend_errors":{k:out["trend"][k] for k in ("expected_max_boundary_error", "june_close_overlap_max_error")}},ensure_ascii=False))


if __name__ == "__main__":
    main()
