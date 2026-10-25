"""Bounded offline experiment; algorithm plan 12.92 / LLD 70.

No source fetch, production calculator, strategy event or peak filter is used.
Run from the repository root with --output reports/xxm_local_extrema_trial_<new>.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import sys
import time
from contextlib import redirect_stdout

from src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import LocalExtremaScanner, number, scan_values
from .peak_image_measurement import measure_original

ROOT = Path(__file__).resolve().parents[4]
PREVIOUS = ROOT / "reports/xxm_peak_annotation_confirmation_20261021_01"
PARAMS = "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3"


@dataclass(frozen=True)
class SavedCase:
    name: str
    path: str
    sha256: str
    rows: int
    frequency: str


CASES = (
    SavedCase("m120_2023", "reports/xxm_m120_reference_trace_20261020_01/source_window.json",
              "044f3b22b341f8b408bc0da430bbf4fe141e21d2aba92d8406020cf076754e18", 72, "120"),
    SavedCase("m90_2023", "reports/xxm_same_day_m90_m120_20230301_20261020_01/m90_source_window.json",
              "95d09af15e5305383a4f88ecdad3d9a3a28135e090b5ed2cea55bc143ccd4797", 63, "90"),
    SavedCase("m90_2026", "reports/xxm_feb25_m90_reference_evidence_20261021_01/source_projection.json",
              "82729d85e277215b54a425d721a1dc393253a3af27c0b46754d1332047917938", 63, "90"),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_rows(rows: list, case: SavedCase) -> dict:
    if not isinstance(rows, list) or len(rows) != case.rows or not rows:
        raise ValueError("Unexpected fixed window length")
    fields = {"trade_time", "trade_date", "close", "macd_dif", "macd_dea", "macd",
              "params_key", "indicator_version"}
    slots = {"11:30:00", "15:00:00"} if case.frequency == "120" else {"11:00:00", "14:00:00", "15:00:00"}
    observed_days: dict[str, set] = defaultdict(set)
    last, maximum_error = None, Decimal(0)
    first_fields = set(rows[0]) if isinstance(rows[0], dict) else set()
    for row in rows:
        if not isinstance(row, dict) or not fields <= set(row) or set(row) != first_fields:
            raise ValueError("Missing or inconsistent producer fields")
        if row["params_key"] != PARAMS or row["indicator_version"] != "1":
            raise ValueError("Changed indicator identity")
        if ("ts_code" in row and row["ts_code"] != "000001.SH") or (
                "freq" in row and row["freq"] != case.frequency):
            raise ValueError("Changed explicit source identity")
        key = row["trade_time"]
        if not isinstance(key, str):
            raise ValueError("Nonstring producer timestamp")
        stamp = datetime.strptime(key, "%Y-%m-%d %H:%M:%S")
        if stamp.date().isoformat() != row["trade_date"] or key[-8:] not in slots:
            raise ValueError("Changed date or within-day period contract")
        if last is not None and key <= last:
            raise ValueError("Duplicate or unordered rows")
        last = key
        values = {}
        for column in ("close", "macd_dif", "macd_dea", "macd"):
            if not isinstance(row[column], str):
                raise ValueError("Producer numeric fields must remain strings")
            values[column] = number(row[column])
        if values["close"] <= 0:
            raise ValueError("Nonpositive source close")
        error = abs(values["macd"] - 2 * (values["macd_dif"] - values["macd_dea"]))
        maximum_error = max(maximum_error, error)
        if error > Decimal("0.0000000001"):
            raise ValueError("Broken H=2*(DIF-DEA)")
        observed_days[row["trade_date"]].add(key[-8:])
    if any(day_slots != slots for day_slots in observed_days.values()):
        raise ValueError("Missing within-day completed periods")
    return dict(rows=len(rows), columns=sorted(first_fields), start=rows[0]["trade_time"],
                end=rows[-1]["trade_time"], observedDates=len(observed_days),
                withinDaySlotsComplete=True, timestampsUniqueAndOrdered=True,
                maxMacdEquationError=str(maximum_error),
                fullCalendarIndependentlyRechecked=False,
                leftBoundaryMayTruncateAnEarlierMove=True)


def read_case(case: SavedCase, root: Path = ROOT) -> tuple[list, dict]:
    path = root / case.path
    if not path.is_file() or path.stat().st_size > 100_000 or sha(path) != case.sha256:
        raise ValueError("Missing, oversized or changed frozen window")
    rows = json.loads(path.read_text())
    return rows, validate_rows(rows, case)


def series_turns(rows: list[dict], field: str) -> tuple[list[dict], dict | None]:
    scanner, turns = LocalExtremaScanner(), []
    for row in rows:
        point = scanner.step(row["trade_time"], row[field])
        if point is not None:
            record = point.record()
            record["close_at_first_peak_sample"] = rows[point.first_index]["close"]
            record["close_at_confirmation"] = row["close"]
            turns.append(record)
    return turns, scanner.pending()


def summarize_case(rows: list[dict], case: SavedCase, quality: dict) -> dict:
    dif, dif_tail = series_turns(rows, "macd_dif")
    hist, hist_tail = series_turns(rows, "macd")
    segments = []
    for index, row in enumerate(rows):
        value = number(row["macd"])
        sign = (value > 0) - (value < 0)
        if not segments or segments[-1]["sign"] != sign:
            segments.append(dict(sign=sign, first=index, last=index))
        segments[-1]["last"] = index
    for segment_index, segment in enumerate(segments):
        part = rows[segment["first"]:segment["last"] + 1]
        segment.update(
            start=part[0]["trade_time"], end=part[-1]["trade_time"],
            leftTruncated=segment_index == 0,
            rightOpen=segment_index == len(segments) - 1,
            difMaxAt=max(part, key=lambda r: number(r["macd_dif"]))["trade_time"],
            difMinAt=min(part, key=lambda r: number(r["macd_dif"]))["trade_time"],
            closeMaxAt=max(part, key=lambda r: number(r["close"]))["trade_time"],
            closeMinAt=min(part, key=lambda r: number(r["close"]))["trade_time"],
        )
        segment["histogramLengthPeaks"] = [
            p for p in hist if segment["first"] <= p["first_index"] <= segment["last"]
            and ((segment["sign"] == 1 and p["kind"] == "MAX")
                 or (segment["sign"] == -1 and p["kind"] == "MIN"))]
        segment["difTurns"] = [p for p in dif if segment["first"] <= p["first_index"] <= segment["last"]]
    # Every prefix is replayed independently; no full-result state is restored.
    prefix_checks = 0
    for field, full in (("macd_dif", dif), ("macd", hist)):
        for length in range(len(rows) + 1):
            prefix, _ = series_turns(rows[:length], field)
            expected = [p for p in full if p["confirmed_index"] < length]
            if prefix != expected:
                raise AssertionError("Past confirmed turns depend on future rows")
            prefix_checks += 1
    return dict(case=case.name, source=case.path, sourceSha256=case.sha256,
                quality=quality, difTurns=dif, histogramTurns=hist,
                difPending=dif_tail, histogramPending=hist_tail, segments=segments,
                count=dict(difTurns=len(dif), histogramTurns=len(hist),
                           histogramLengthPeaks=sum(len(s["histogramLengthPeaks"]) for s in segments),
                           colourSegments=sum(s["sign"] != 0 for s in segments),
                           segmentsWithMultipleLengthPeaks=sum(len(s["histogramLengthPeaks"]) > 1 for s in segments)),
                independentPrefixChecks=prefix_checks,
                newSoftwareLabels=0, algorithmEventsGenerated=0)


def literal_anchor_checks(results: list[dict]) -> list[dict]:
    # Expected times come from the pre-implementation source review, LLD 70.2.
    expected = (
        ("m120_2023", "difTurns", "MAX", "2023-02-02 11:30:00", "2023-02-02 15:00:00"),
        ("m90_2026", "histogramTurns", "MAX", "2026-02-10 14:00:00", "2026-02-10 15:00:00"),
        ("m90_2026", "histogramTurns", "MAX", "2026-02-11 11:00:00", "2026-02-11 14:00:00"),
        ("m90_2026", "difTurns", "MAX", "2026-02-12 15:00:00", "2026-02-13 11:00:00"),
    )
    indexed = {r["case"]: r for r in results}
    checks = []
    for name, field, kind, at, known in expected:
        matches = [p for p in indexed[name][field] if p["kind"] == kind and p["first_at"] == at]
        if len(matches) != 1 or matches[0]["confirmed_at"] != known:
            raise AssertionError("Independent real literal anchor failed")
        checks.append(dict(case=name, series=field, expectedPeak=at, expectedKnownAt=known, passed=True))
    return checks


def benchmark(deadline: float) -> list[dict]:
    result = []
    for size in (1_000, 10_000, 100_000):
        started, scanner, count = time.perf_counter(), LocalExtremaScanner(), 0
        for index in range(size):
            if index % 1000 == 0 and time.perf_counter() > deadline:
                raise TimeoutError("Local study budget exceeded")
            count += scanner.step(f"{index:09d}", (0, 1, 2, 1, 0)[index % 5]) is not None
        result.append(dict(samples=size, turns=count, seconds=time.perf_counter() - started,
                           retainedScannerFields=len(vars(scanner)), generatedNotMarketData=True))
    return result


def save_new(out: Path, name: str, value) -> None:
    path = out / name
    if path.exists():
        raise ValueError("Refusing to overwrite experiment unit")
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(payload.encode()) > 4_000_000:
        raise ValueError("Oversized experiment unit")
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(payload)
    os.replace(partial, path)
    if sum(p.stat().st_size for p in out.iterdir() if p.is_file()) > 16_000_000:
        raise ValueError("Experiment exceeds output budget")


def protected_files() -> dict[str, str]:
    previous = json.loads((PREVIOUS / "run.json").read_text())["protected"]
    for path in PREVIOUS.iterdir():
        if path.is_file():
            previous[str(path.relative_to(ROOT))] = sha(path)
    return previous


def assert_protected(files: dict[str, str]) -> None:
    changed = [name for name, digest in files.items() if sha(ROOT / name) != digest]
    if changed:
        raise ValueError("Changed protected evidence: " + ", ".join(changed))


def notebook(out: Path) -> None:
    """Small reader-facing companion; implementation stays in the theme modules."""
    cells = [
        ("markdown", "## tl;dr\n本文件顺序复查字面示例、三个真实小窗口和图像测量边界。只读，不生成结构信号。"),
        ("markdown", "## Context & Methods\n无过滤的局部转折；后续已完成点确认此前峰。图像像素不是原始指标。\n### Key Assumptions\n原三个JSON及图片SHA不变；时间为上海交易时间。"),
        ("code", f"from pathlib import Path\nimport json, sys\nroot = Path({str(ROOT)!r})\nsys.path.insert(0, str(root))\nfrom src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import scan_values\nfrom scripts.research.index_market.xxm.local_extrema_study import CASES, read_case, summarize_case\nexample = scan_values([2,5,8,6,3,4,6,4])\nassert [(p.kind, str(p.value)) for p in example] == [('MAX','8'),('MIN','3'),('MAX','6')]\nprint([(p.kind, str(p.value), p.first_index, p.confirmed_index) for p in example])"),
        ("markdown", "## Data\n三个既存窗口共198行；各自路径与SHA在CASES和执行manifest中，未读取正式源。"),
        ("code", "recomputed = []\nfor case in CASES:\n    rows, quality = read_case(case)\n    result = summarize_case(rows, case, quality)\n    recomputed.append(result)\n    print(case.name, quality['rows'], result['count'], result['independentPrefixChecks'])"),
        ("markdown", "## Results\n以下输出与完成的试验文件比对；不会将单元测试通过解释为作者一致性通过。"),
        ("code", f"report = Path({str(out)!r})\nfor result in recomputed:\n    saved = json.loads((report / (result['case'] + '.json')).read_text())\n    assert result == saved\nimage = json.loads((report / 'image_measurement.json').read_text())\nprint('图片独立三峰数值验证:', image['independentThreePeakValidation'])\nfor variant in image['variants']:\n    print(variant['spec']['name'], '柱组', len(variant['bars']), '遮挡', variant['censored_bars'], '断点', len(variant['gaps']))"),
        ("markdown", "## Takeaways\n基础数学行为与三个小窗口可复查；额外转折全部保留。盘口原图遮挡及未知原始柱值限制作者一致性判断；下一步不能只凭程序运行成功就迁移产品。"),
    ]
    context, rendered, count = {}, [], 0
    for index, (kind, source) in enumerate(cells):
        cell = dict(cell_type=kind, id=f"local-turn-{index}", metadata={}, source=source)
        if kind == "code":
            count += 1
            stream = io.StringIO()
            with redirect_stdout(stream):
                exec(compile(source, f"local_extrema_review.ipynb:cell-{index}", "exec"), context)
            cell.update(execution_count=count, outputs=[dict(output_type="stream", name="stdout", text=stream.getvalue())])
        rendered.append(cell)
    value = dict(cells=rendered, nbformat=4, nbformat_minor=5,
                 metadata=dict(language_info=dict(name="python", version="3"),
                               execution_method="Sequential Python cells; no Jupyter kernel installed or claimed"))
    save_new(out, "review.ipynb", value)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    out = Path(args.output).resolve()
    if out.parent != ROOT / "reports" or not out.name.startswith("xxm_local_extrema_trial_"):
        raise ValueError("Use a new reports/xxm_local_extrema_trial_<batch> directory")
    if out.exists():
        raise ValueError("Refusing existing output directory")
    protected = protected_files()
    assert_protected(protected)
    started, deadline = time.perf_counter(), time.perf_counter() + 60
    out.mkdir()
    code_paths = (
        "src/biz/services/wealth/market/index_detail_daily_wave/local_extrema.py",
        "scripts/research/index_market/xxm/local_extrema_study.py",
        "scripts/research/index_market/xxm/peak_image_measurement.py",
        "scripts/research/index_market/tests/test_xxm_local_extrema.py",
        "scripts/research/index_market/tests/test_xxm_local_extrema_study.py",
    )
    save_new(out, "run.json", dict(status="RUNNING", protected=protected,
                                  authorization="管理员按12.91方法推进并完成试验后报告", protectedCount=len(protected),
                                  sources=[dict(name=c.name, path=c.path, sha256=c.sha256, rows=c.rows) for c in CASES],
                                  codeSha256={p: sha(ROOT / p) for p in code_paths},
                                  codeGraphReview=dict(tool="codegraph_explore", calls=2,
                                      symbols=["XxmCalculator", "TopCurrentCloseCalculator", "PriceBeforeSelectionCalculator", "NearFirstCalculator", "ReturnReferenceCalculator"],
                                      conclusion="Existing whole-period runners are not reused; new pure scanner has only new research/test consumers. No API or frontend changes.")))
    results = []
    for case in CASES:
        if time.perf_counter() > deadline:
            raise TimeoutError("Study deadline exceeded")
        rows, quality = read_case(case)
        result = summarize_case(rows, case, quality)
        save_new(out, case.name + ".json", result)
        results.append(result)
    anchors = literal_anchor_checks(results)
    image_path = ROOT / "reports/xxm_peak_comparison_images_20261021_01/02_near_and_skipped_peak.png"
    if str(image_path.relative_to(ROOT)) not in protected or sha(image_path) != protected[str(image_path.relative_to(ROOT))]:
        raise ValueError("Unprotected original image")
    image = measure_original(image_path)
    image.update(source=str(image_path.relative_to(ROOT)), sourceSha256=sha(image_path))
    save_new(out, "image_measurement.json", image)
    timings = benchmark(deadline)
    save_new(out, "benchmark.json", timings)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        rss *= 1024
    if rss > 256 * 1024 * 1024:
        raise MemoryError("Study exceeds 256MiB resident memory")
    summary = dict(
        status="ANALYSIS_COMPUTED_AUTHOR_VALIDATION_LIMITS", date="2026-10-21", rows=sum(c.rows for c in CASES),
        cases=[dict(case=r["case"], **r["count"]) for r in results],
        independentPrefixChecks=sum(r["independentPrefixChecks"] for r in results),
        realLiteralAnchorChecks=anchors, codeBehaviorValidated=True, authorRuleFullyValidated=False,
        imageRawIndicatorValuesAvailable=False, imageIndependentThreePeakValidation=False,
        noNewFiltering=True, noProductionCodeChanged=True, noNewSoftwareLabels=True,
        seconds=time.perf_counter() - started, peakRssBytes=rss,
    )
    save_new(out, "summary.json", summary)
    notebook(out)
    assert_protected(protected)
    if time.perf_counter() > deadline:
        raise TimeoutError("Final verification exceeded study budget")
    save_new(out, "completion.json", dict(status="COMPLETED_WITH_AUTHOR_VALIDATION_LIMITS", allProtectedUnchanged=True,
                                          protectedFiles=len(protected), seconds=time.perf_counter() - started,
                                          notebookCellsExecutedSequentially=True))
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
