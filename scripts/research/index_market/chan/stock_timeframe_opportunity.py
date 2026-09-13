"""60-minute opportunity study from authenticated 30-minute QFQ research input."""

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import time

from scripts.research.index_market.chan import stock_opportunity as base
from scripts.research.index_market.chan import stock_opportunity_filters as filters
from scripts.research.index_market.chan.minute_data import slots
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_qfq_model import SPEC as QFQ_SPEC
from scripts.research.index_market.chan.stock_qfq_run import run_signals, source_gate


@dataclass(frozen=True)
class TimeframeSpec:
    frequency: int = 60
    source_frequency: int = 30
    group_size: int = 2
    seconds: int = 180
    replay_seconds: int = 30
    output_bytes: int = 32 * 1024**2
    old_filters: str = "reports/stock_opportunity_filters_002245_30m_20260912"


SPEC = TimeframeSpec()


def aggregate_bars(rows):
    if not rows or len(rows) % 8 or len(rows) > base.SPEC.max_bars:
        raise ValueError("incomplete day or bar budget")
    result = []
    previous = ""
    for first in range(0, len(rows), 8):
        day = rows[first]["date"]
        batch = rows[first : first + 8]
        if day <= previous or [r["time"] for r in batch] != [
            f"{day} {s}" for s in slots(30)
        ]:
            raise ValueError("missing/duplicate/unsorted source grid")
        if any(
            r["code"] != QFQ_SPEC.code
            or r["frequency"] != 30
            or r["price_basis"] != "qfq"
            or r["date"] != day
            for r in batch
        ):
            raise ValueError("source identity/basis mismatch")
        previous = day
        for offset in range(0, 8, SPEC.group_size):
            a, b = batch[offset : offset + SPEC.group_size]
            row = dict(
                a,
                frequency=SPEC.frequency,
                time=b["time"],
                start_time=(
                    datetime.fromisoformat(a["time"]) - timedelta(minutes=30)
                ).isoformat(sep=" "),
                source_start=first + offset,
                source_end=first + offset + 1,
                high=max(a["high"], b["high"]),
                low=min(a["low"], b["low"]),
                close=b["close"],
                vol=a["vol"] + b["vol"],
                amount=a["amount"] + b["amount"],
            )
            result.append(row)
    return result


def project(event, aggregated):
    """Reindex observation timestamps, not the original signal-generation timeframe."""
    result = dict(
        event,
        detection_signal_index=event["signal_index"],
        detection_anchor_index=event["anchor_index"],
        observation_frequency=30,
    )
    for key in ("signal_index", "start_index", "end_index", "anchor_index"):
        result[key] = aggregated[event[key]]["source_end"]
    return result


def attach_detection_indices(result, aggregated):
    mapping = {r["source_end"]: i for i, r in enumerate(aggregated)}
    for event in result["events"]:
        event["detection_signal_index"] = mapping[event["index"]]
        event["detection_frequency"] = SPEC.frequency
        event["observation_frequency"] = SPEC.source_frequency


def compare_report(results, old_results):
    def pct(v):
        return "无样本" if v is None else f"{v:.2%}"

    text = """# 蔚蓝锂芯：60分钟与30分钟买点对照

输入2021-09-09—2026-09-08，同一前复权基准，250交易日初始化。60分钟由每日两根30分钟合成，共4840根；买点在60分钟重新识别，MA40/ATR20亦按60分钟柱计算。参数柱数不变，物理时间变长。

主窗口仍为确认后的10个交易日，下一柱开盘进入；收益和±5%先触顺序在原30分钟行情观察，所有周期均观察同样2400个交易分钟。不是账户净收益，不含费用和成交保证。

| 周期 | 过滤 | 信号数 | 上涨率 | 均值 | 匹配普通均值 | 非重叠数/均值/超额 | 早期覆盖 |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
"""
    for frequency, data in [(30, old_results), (60, results)]:
        for name, r in data.items():
            s = next(
                x for x in r["summary"] if x["group"] == "ALL" and x["horizon"] == 10
            )
            a = s["signals"]
            n = s["nonoverlap_comparison"]
            text += f"| {frequency}分钟 | {name} | {a['n']} | {pct(a.get('win'))} | {pct(a.get('mean'))} | {pct(s['matched'].get('mean'))} | {n['signals']['n']}/{pct(n['signals'].get('mean'))}/{pct(n['excess'])} | {r['recall']['early_count']}/{r['recall']['n']} |\n"
    text += """
四组original/trend/near/both分别为原买点/仅顺势/仅不追高/同时满足。匹配同年同确认时段，不是同趋势状态的因果对照；固定24段上涨标签未随周期改变。完整B1/B2/B3、5/10/20日、逐年、去掉最高一例、尾部不足及先触价数据见各组JSON。

信号及前缀/未来扰动/缩放/短初始化检查见signal_checks.json；聚合输入见input_60.json，原始首次事件见full_events.json，features.json是60分钟指标；evaluation中的index是原30分钟观察索引，detection_signal_index保留60分钟索引。严禁把两类索引混用。

本股历史已被多轮查看；周期对照为探索性分析，不是新未见测试，不以最高收益周期宣称有效。90分钟尚待日内短尾柱或跨日连续分段选择，本报告没有90分钟结果。无产品/正式数据写入。
"""
    return text


def execute(output):
    started = time.monotonic()
    output = base.safe_output(output)
    source = base.REPO / base.SPEC.source
    old_folder = base.REPO / SPEC.old_filters
    source_manifest = filters.checked_report(source)
    old_manifest = filters.checked_report(old_folder)
    # Authenticate every transitive research dependency retained by the source run.
    for name, expected in source_manifest["code_sha256"].items():
        if base.sha(Path(__file__).with_name(name)) != expected:
            raise ValueError(f"frozen source dependency changed: {name}")
    for path, expected in old_manifest["code_sha256"].items():
        if base.sha(Path(path)) != expected:
            raise ValueError(f"frozen evaluator changed: {path}")
    source_info = source_gate()
    original = json.loads((source / "input.json").read_text())
    rows = aggregate_bars(original)
    old_results = {
        v: json.loads((old_folder / f"{v}.json").read_text())
        for v in filters.SPEC.variants
    }
    output.mkdir()
    paths = [Path(__file__), Path(base.__file__), Path(filters.__file__)]
    receipt = dict(
        status="running",
        spec=asdict(SPEC),
        filter_spec=asdict(filters.SPEC),
        observation_spec=asdict(base.SPEC),
        source=source_info,
        source_manifest_sha256=base.sha(source / "manifest.json"),
        previous_manifest_sha256=base.sha(old_folder / "manifest.json"),
        plan_sha256_at_start=base.sha(base.REPO / filters.SPEC.plan),
        code_sha256={str(p): base.sha(p) for p in paths},
    )
    try:
        save(output / "input_60.json", rows)
        run_spec = replace(
            QFQ_SPEC,
            frequency=SPEC.frequency,
            total_seconds=SPEC.seconds,
            replay_seconds=SPEC.replay_seconds,
        )
        events, _, checks = run_signals(rows, output, started, run_spec)
        buys = [e for e in events if e["group"] in ("B1", "B2", "B3")]
        fs = [filters.features(rows, e) for e in buys]
        if any(
            filters.features(rows[: e["signal_index"] + 1], e) != f
            for e, f in zip(buys, fs, strict=True)
        ):
            raise ValueError("filter prefix mismatch")
        save(output / "features.json", fs)
        results = {}
        for v in filters.SPEC.variants:
            if time.monotonic() - started > SPEC.seconds:
                raise TimeoutError("timeframe experiment budget")
            selected = [
                project(e, rows)
                for e, f in zip(buys, fs, strict=True)
                if filters.passes(f, v)
            ]
            r = base.evaluate(original, selected)
            attach_detection_indices(r, rows)
            if [
                (x["entry_index"], x["exit_index"]) for x in r["recall"]["rallies"]
            ] != [
                (x["entry_index"], x["exit_index"])
                for x in old_results["original"]["recall"]["rallies"]
            ]:
                raise ValueError("rally labels changed")
            filters.enrich(original, r)
            for s in r["summary"]:
                origin = next(
                    x
                    for x in (r if v == "original" else results["original"])["summary"]
                    if x["group"] == s["group"] and x["horizon"] == s["horizon"]
                )
                s["removed"] = origin["total"] - s["total"]
            results[v] = r
            save(output / f"{v}.json", r)
        (output / "report.md").write_text(compare_report(results, old_results))
        if (
            time.monotonic() - started > SPEC.seconds
            or sum(p.stat().st_size for p in output.iterdir()) > SPEC.output_bytes
        ):
            raise ValueError("time/output budget")
        receipt.update(
            status="complete"
            if checks["all_passed"]
            else "complete_with_signal_stability_differences",
            seconds=time.monotonic() - started,
            filter_prefix=True,
            all_signal_checks_passed=checks["all_passed"],
            bars=len(rows),
        )
    except BaseException as exc:
        receipt.update(status="failed", error=str(exc))
        raise
    finally:
        receipt["artifacts_sha256"] = {p.name: base.sha(p) for p in output.iterdir()}
        save(output / "manifest.json", receipt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    execute(parser.parse_args().output)
