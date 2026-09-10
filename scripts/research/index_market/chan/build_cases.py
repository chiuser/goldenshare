"""Bounded, read-only input; educational replay, not a trading backtest."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[4]
OUT: Path  # Set only by an explicitly validated --output directory.
COMMIT = "429d6ed3043e27c93a003ba2b10e70a05575e1f5"
CONFIG = dict(trigger_step=True, bi_algo="normal", bi_strict=True,
              bi_fx_check="strict", gap_as_kl=False, bi_end_is_peak=True,
              bi_allow_sub_peak=True, seg_algo="chan", left_seg_method="peak",
              zs_algo="normal", zs_combine=True, zs_combine_mode="zs",
              one_bi_zs=False, divergence_rate=1.0, macd_algo="peak",
              max_bs2_rate=0.9999)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def sqlstr(value):
    return "'" + str(value).replace("'", "''") + "'"


def read_input():
    root = Path("/Volumes/datasource/data_lake/silver/index_daily")
    files = sorted(p / "part-000.parquet" for p in root.iterdir()
                   if p.is_dir() and "trade_date=2024-01-01" <= p.name <= "trade_date=2025-12-31")
    assert 0 < len(files) <= 600
    entries = []
    for p in files:
        assert p.is_file()
        entries.append(dict(path=str(p), bytes=p.stat().st_size,
                            sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    total = sum(e["bytes"] for e in entries)
    assert total <= 32 * 1024**2
    paths = "[" + ",".join(sqlstr(p) for p in files) + "]"
    sql = f"""SET memory_limit='1GiB'; SET threads=4; SET max_temp_directory_size='0B';
SET allowed_paths={paths}; SET enable_external_access=false;
SET allow_persistent_secrets=false; SET lock_configuration=true;
SELECT CAST(trade_date AS VARCHAR) AS date, open, high, low, close, filename
FROM read_parquet({paths}, hive_partitioning=false, filename=true)
WHERE ts_code='000300.SH' ORDER BY trade_date;"""
    start = time.monotonic()
    proc = subprocess.run(["duckdb", "-json", ":memory:"], input=sql, text=True,
                          capture_output=True, check=True, timeout=30)
    rows = json.loads(proc.stdout)
    assert len(rows) == len(files) <= 600
    assert len({r["date"] for r in rows}) == len(rows)
    for r in rows:
        assert f"trade_date={r['date']}" in r["filename"]
        assert all(isinstance(r[k], (int, float)) and math.isfinite(r[k]) and r[k] > 0
                   for k in ("open", "high", "low", "close"))
        assert r["low"] <= min(r["open"], r["close"]) <= max(r["open"], r["close"]) <= r["high"]
    return rows, entries, time.monotonic() - start


def replay(rows):
    from ChanConfig import CChanConfig
    from Common.CEnum import KL_TYPE
    from Common.CTime import CTime
    from KLine.KLine_List import CKLine_List
    from KLine.KLine_Unit import CKLine_Unit

    kl = CKLine_List(KL_TYPE.K_DAY, CChanConfig(dict(CONFIG)))
    frames = []
    prev = None
    start = time.monotonic()
    for i, row in enumerate(rows):
        assert time.monotonic() - start < 60
        y, m, d = map(int, row["date"].split("-"))
        unit = CKLine_Unit(dict(time_key=CTime(y, m, d, 0, 0),
                               **{k: row[k] for k in ("open", "high", "low", "close")}))
        unit.set_idx(i)
        unit.kl_type = KL_TYPE.K_DAY
        if prev is not None:
            unit.set_pre_klu(prev)
        kl.add_single_klu(unit)
        prev = unit

        def line(b):
            return dict(idx=b.idx, start=b.get_begin_klu().idx, end=b.get_end_klu().idx,
                        a=b.get_begin_val(), b=b.get_end_val(), sure=b.is_sure, direction=b.dir.name)

        frames.append(dict(asof=row["date"], index=i,
                           combined=[dict(start=k.lst[0].idx, end=k.lst[-1].idx,
                                          high=k.high, low=k.low, fx=k.fx.name,
                                          raw=[u.idx for u in k.lst]) for k in kl.lst],
                           bi=[line(b) for b in kl.bi_list],
                           seg=[line(b) for b in kl.seg_list],
                           zs=[dict(start=z.begin.idx, end=z.end.idx, low=z.low, high=z.high,
                                    peak_low=z.peak_low, peak_high=z.peak_high, sure=z.is_sure)
                               for z in kl.zs_list],
                           bsp=[dict(anchor=b.klu.idx, buy=b.is_buy, types=b.type2str(), bi_sure=b.bi.is_sure)
                                for b in kl.bs_point_lst.bsp_store_flat_dict.values()]))
    return frames


def collect(rows, frames):
    events = []
    for prev, cur in zip(frames, frames[1:]):
        if cur["asof"] < "2025-01-01":
            continue
        old = {b["idx"]: b for b in prev["bi"]}
        new = {b["idx"]: b for b in cur["bi"]}
        for idx, b in old.items():
            if idx in new and (b["end"] != new[idx]["end"] or b["sure"] != new[idx]["sure"]):
                events.append(dict(asof=cur["asof"], before_asof=prev["asof"], before=b, after=new[idx]))
    first_inclusion = next(dict(asof=f["asof"], combined=f["combined"][-1])
                           for f in frames if f["asof"] >= "2025-01-01" and len(f["combined"][-1]["raw"]) > 1)
    seen = set()
    first_fractal = None
    for f in frames:
        for k in f["combined"]:
            key = (k["start"], k["end"], k["fx"])
            if k["fx"] != "UNKNOWN" and key not in seen and rows[k["start"]]["date"] >= "2025-01-01" and first_fractal is None:
                first_fractal = dict(asof=f["asof"], combined=k)
            seen.add(key)
    sure_changed = [e for e in events if e["before"]["sure"] and e["before"]["end"] != e["after"]["end"]]
    return dict(first_inclusion=first_inclusion, first_fractal=first_fractal,
                bi_changes=events, previously_sure_endpoint_changes=sure_changed,
                final_counts={k: len(frames[-1][k]) for k in ("combined", "bi", "seg", "zs", "bsp")})


def render(rows, frames, evidence):
    from PIL import Image, ImageDraw, ImageFont
    fontpath = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    font = lambda n: ImageFont.truetype(fontpath, n)
    colors = dict(text="#243344", grid="#e2e8ee", blue="#2463b4", orange="#c56b16", up="#b5513a", down="#427565")

    def panel(draw, box, fr, lo_idx, hi_idx, yrange=None, show_zs=False):
        left, top, right, bottom = box
        sample = rows[lo_idx:hi_idx+1]
        ymin, ymax = yrange or (min(r["low"] for r in sample)-30, max(r["high"] for r in sample)+30)
        x = lambda i: left + (i-lo_idx+.5)/(hi_idx-lo_idx+1)*(right-left)
        y = lambda v: bottom - (v-ymin)/(ymax-ymin)*(bottom-top)
        for j in range(5):
            val = ymin + (ymax-ymin)*j/4
            yy = y(val)
            draw.line((left, yy, right, yy), fill=colors["grid"])
            draw.text((left-64, yy-10), f"{val:.0f}", font=font(17), fill=colors["text"])
        if show_zs:
            for z in fr["zs"]:
                if z["end"] < lo_idx or z["start"] > hi_idx:
                    continue
                draw.rectangle((x(max(lo_idx,z["start"])),y(z["high"]),x(min(hi_idx,z["end"])),y(z["low"])),
                               fill="#e9e4f3", outline="#9e8bb9", width=2)
        candle_w = max(2, min(7, int((right-left)/(hi_idx-lo_idx+1)*.26)))
        for i in range(lo_idx, min(hi_idx,fr["index"])+1):
            r=rows[i]; xx=x(i); c=colors["up"] if r["close"]>=r["open"] else colors["down"]
            draw.line((xx,y(r["high"]),xx,y(r["low"])), fill=c, width=1)
            draw.rectangle((xx-candle_w,y(max(r["open"],r["close"])),xx+candle_w,max(y(min(r["open"],r["close"])), y(max(r["open"],r["close"]))+1)),fill=c)
        for b in fr["bi"]:
            if b["start"] < lo_idx or b["end"] > hi_idx:
                continue
            xy=(x(b["start"]),y(b["a"]),x(b["end"]),y(b["b"]))
            c=colors["blue"] if b["sure"] else colors["orange"]
            if b["sure"]:
                draw.line(xy,fill=c,width=3)
            else:
                steps=40
                for n in range(0,steps,2):
                    draw.line(tuple(xy[j]+(xy[j+2]-xy[j])*t/steps for t in (n,n+1) for j in (0,1)),fill=c,width=3)
            draw.ellipse((xy[2]-4,xy[3]-4,xy[2]+4,xy[3]+4),fill=c)
        for i in sorted(set([lo_idx, (lo_idx+hi_idx)//2, hi_idx])):
            draw.text((x(i)-42,bottom+12),rows[i]["date"][5:],font=font(17),fill=colors["text"])

    bydate={f["asof"]: f for f in frames}
    start_idx=next(i for i,r in enumerate(rows) if r["date"] >= "2024-12-02")
    fr=bydate["2025-03-31"]
    im=Image.new("RGB",(1440,800),"white"); d=ImageDraw.Draw(im)
    d.text((48,30),"沪深300：截至 2025-03-31 收盘的日 K 结构",font=font(32),fill=colors["text"])
    d.text((48,85),"蓝实线 = 当帧 sure；橙虚线 = 当帧未完成；紫框 = 该实现的未完成笔级中枢",font=font(22),fill=colors["text"])
    visible_zs=[z for z in fr["zs"] if z["end"]>=start_idx]
    yrange=(min([r["low"] for r in rows[start_idx:fr["index"]+1]]+[z["low"] for z in visible_zs])-30,
            max([r["high"] for r in rows[start_idx:fr["index"]+1]]+[z["high"] for z in visible_zs])+30)
    panel(d,(115,155,1385,650),fr,start_idx,fr["index"],yrange,show_zs=True)
    d.text((48,718),"纵轴：指数点（局部截轴）  |  横轴：等距交易日  |  原始 OHLC 未做包含合并",font=font(20),fill=colors["text"])
    d.text((48,755),"输入从 2024-01-02 开始；只展示局部。历史截断回放，不代表买卖建议或收益验证。",font=font(19),fill=colors["text"])
    im.save(OUT/"csi300_structure.png")

    event=evidence["previously_sure_endpoint_changes"][0]
    idx=bydate[event["asof"]]["index"]
    later=min(idx+5,len(frames)-1)
    selected=[bydate[event["before_asof"]],frames[idx],frames[later]]
    lo=max(0,event["before"]["start"]-3); hi=later
    ymin=min(r["low"] for r in rows[lo:hi+1])-30; ymax=max(r["high"] for r in rows[lo:hi+1])+30
    im=Image.new("RGB",(1440,1370),"white"); d=ImageDraw.Draw(im)
    d.text((48,25),"同一笔如何变化：每天只追加当天已收盘的 K 线",font=font(32),fill=colors["text"])
    for j,f in enumerate(selected):
        yy=90+j*395
        b=next((b for b in f["bi"] if b["idx"]==event["before"]["idx"]),None)
        desc=f"截至 {f['asof']}"
        if b:
            desc+=f"  |  笔 #{b['idx']} 端点 {rows[b['end']]['date']} / {b['b']:.2f}  |  sure={b['sure']}"
        d.text((55,yy),desc,font=font(23),fill=colors["text"])
        panel(d,(115,yy+55,1385,yy+325),f,lo,hi,(ymin,ymax))
    d.text((48,1290),"三图共用坐标。右侧空白表示当时尚未输入，不是缺失行情。",font=font(21),fill=colors["text"])
    d.text((48,1325),"sure 是程序当帧状态，不是永不重画承诺。点位发生日期 ≠ 当时可识别日期。",font=font(21),fill=colors["text"])
    im.save(OUT/"endpoint_replay.png")
    evidence["replay_chart_dates"]=[f["asof"] for f in selected]


def main():
    global OUT
    parser=argparse.ArgumentParser(); parser.add_argument("--chan-source",type=Path,required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory under repository reports")
    args=parser.parse_args()
    OUT = args.output.resolve()
    if OUT == REPO / "reports" or not OUT.is_relative_to(REPO / "reports"):
        raise ValueError("output must be a new child directory under repository reports")
    if OUT.exists():
        raise ValueError("refusing to overwrite an existing report directory")
    actual=subprocess.check_output(["git","-C",str(args.chan_source),"rev-parse","HEAD"],text=True).strip()
    assert actual==COMMIT, actual
    assert not subprocess.check_output(["git","-C",str(args.chan_source),"diff","HEAD","--"],text=True)
    sys.path.insert(0,str(args.chan_source.resolve()))
    OUT.mkdir(parents=True, exist_ok=False)
    rows,files,seconds=read_input()
    start=time.monotonic(); frames=replay(rows); elapsed=time.monotonic()-start
    evidence=collect(rows,frames)
    checks=[]
    for date in ("2025-01-10","2025-03-31","2025-06-30","2025-09-30","2025-12-31"):
        idx=next(i for i,r in enumerate(rows) if r["date"]==date)
        assert replay(rows[:idx+1])[-1]==frames[idx]
        checks.append(date)
    render(rows,frames,evidence)
    save("source.json",rows); save("frames.json",frames); save("evidence.json",evidence)
    manifest=dict(symbol="000300.SH",frequency="daily",window=[rows[0]["date"],rows[-1]["date"]],
                  rows=len(rows),files=len(files),source_bytes=sum(f["bytes"] for f in files),
                  source_sha256=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(),
                  chan_commit=COMMIT,config=CONFIG,query_seconds=seconds,replay_seconds=elapsed,
                  prefix_consistency_passes=checks,calendar_coverage="One row per observed partition; no independent exchange-calendar completeness assertion",
                  source_files=files)
    save("manifest.json",manifest)
    print(json.dumps(dict(rows=len(rows),query_seconds=seconds,replay_seconds=elapsed,
                          prefix_checks=checks,first_inclusion=evidence["first_inclusion"],
                          first_fractal=evidence["first_fractal"],
                          first_sure_change=evidence["previously_sure_endpoint_changes"][:1],
                          final_counts=evidence["final_counts"]),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
