"""Frozen conditional-statistics follow-up inside the original training period only."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from scripts.research.index_market.statistics import index_probability_backtest as first
from scripts.research.index_market.statistics.provenance import verify_prior_source


@dataclass(frozen=True)
class ConditionSpec:
    experiment_id: str = "index-condition-statistics-v1"
    source_end: str = "2021-09-07"
    signal_start: str = "2010-02-01"
    signal_end: str = "2021-09-06"
    expected_training_days: int = 2820
    phases: tuple[str, ...] = ("D", "V1", "V2")
    low_quantile: float = 1/3
    high_quantile: float = 2/3
    volatility_quantile: float = 0.5
    block_days: int = 20
    bootstrap_samples: int = 10000
    bootstrap_batch: int = 100
    minimum_group_size: int = 50
    minimum_valid_bootstrap: float = 0.99
    seed: int = 20260908
    family_size: int = 48
    alpha: float = 0.05
    max_files: int = 3000
    max_bytes: int = 256 * 1024**2
    max_rows: int = 9000
    max_seconds: int = 180
    metrics: tuple[str, ...] = ("up_rate", "mean_return", "mean_abs_return", "mean_downside")
    tested_metrics: tuple[str, ...] = ("up_rate", "mean_abs_return")


SPEC = ConditionSpec()
PRIOR_RUN = first.REPO / "reports/index_probability_backtest_v1_20260908_approved"
VIEWS = {"amount": "a20", "volume": "v20"}


def split_training(features: pd.DataFrame, spec: ConditionSpec = SPEC):
    required = ["r1", "r5", "r20", "sigma20", "a20", "v20", "target_date", "next_return", "y"]
    usable = features.dropna(subset=required).copy()
    if (usable.trade_date > spec.signal_end).any() or (usable.target_date > spec.source_end).any():
        raise ValueError("original test period must not enter conditional statistics")
    days = sorted(usable.trade_date.unique())
    if len(days) != spec.expected_training_days:
        raise ValueError("original training-day count differs from frozen first run")
    for code in first.SPEC.codes:
        if sorted(usable.loc[usable.ts_code == code, "trade_date"].unique()) != days:
            raise ValueError("training date set differs across indices")
    if pd.Timestamp(days[0]) != pd.Timestamp(spec.signal_start) or pd.Timestamp(days[-1]) != pd.Timestamp(spec.signal_end):
        raise ValueError("training date endpoints differ from frozen first run")
    step = len(days)//3
    cuts = [0, step, 2*step, len(days)]
    retained, excluded, summaries = [], [], []
    for i, phase in enumerate(spec.phases):
        part = usable[usable.trade_date.isin(days[cuts[i]:cuts[i+1]])].copy()
        part["phase"] = phase
        nominal_n = len(part)//len(first.SPEC.codes)
        if i < 2:
            boundary = pd.Timestamp(days[cuts[i+1]])
            removed = part[part.target_date >= boundary].copy()
            removed["reason"] = "label_crosses_next_phase"
            excluded.append(removed[["ts_code", "trade_date", "target_date", "phase", "reason"]])
            part = part[part.target_date < boundary].copy()
        retained.append(part)
        summaries.append({
            "phase": phase, "nominal_per_index": nominal_n, "actual_per_index": len(part)//3,
            "signal_start": str(part.trade_date.min().date()),
            "signal_end": str(part.trade_date.max().date()),
            "target_end": str(part.target_date.max().date()),
            "purged_per_index": nominal_n-len(part)//3,
        })
    return pd.concat(retained, ignore_index=True), pd.concat(excluded, ignore_index=True), summaries


def fit_thresholds(discovery: pd.DataFrame, spec: ConditionSpec = SPEC) -> dict:
    if discovery.empty or set(discovery.phase) != {"D"}:
        raise ValueError("thresholds may only be fitted on discovery phase D")
    thresholds = {}
    for code in first.SPEC.codes:
        part = discovery[discovery.ts_code == code]
        if part.empty:
            raise ValueError("missing discovery index")
        thresholds[code] = {
            "fit_start": str(part.trade_date.min().date()),
            "fit_end": str(part.trade_date.max().date()), "n": len(part),
            "sigma20_median": float(part.sigma20.quantile(spec.volatility_quantile)),
        }
        for view, field in VIEWS.items():
            low = float(part[field].quantile(spec.low_quantile))
            high = float(part[field].quantile(spec.high_quantile))
            if not np.isfinite([low, high]).all() or low >= high:
                raise ValueError("activity thresholds collapse or are nonfinite")
            thresholds[code][view] = {"low": low, "high": high, "low_ratio": math.exp(low), "high_ratio": math.exp(high)}
    return thresholds


def assign_groups(frame: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    parts = []
    for code in first.SPEC.codes:
        part = frame[frame.ts_code == code].copy()
        threshold = thresholds[code]
        part["trend"] = np.where(part.r5 > 0, "up", np.where(part.r5 < 0, "down", "flat"))
        part["volatility"] = np.where(part.sigma20 <= threshold["sigma20_median"], "low", "high")
        for view, field in VIEWS.items():
            activity = np.where(part[field] <= threshold[view]["low"], "low",
                                np.where(part[field] >= threshold[view]["high"], "high", "middle"))
            part[f"{view}_activity"] = activity
            eligible = (part.trend != "flat") & (activity != "middle")
            group = (part.trend == "up").astype(int)*4 + (part.volatility == "high").astype(int)*2 + (activity == "high").astype(int)
            part[f"{view}_group"] = np.where(eligible, group, -1)
            part[f"{view}_exclusion"] = np.where(part.trend == "flat", "flat_r5",
                                                np.where(activity == "middle", "middle_activity", "included"))
        parts.append(part)
    return pd.concat(parts, ignore_index=True).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def outcomes(frame: pd.DataFrame) -> np.ndarray:
    r = frame.next_return.to_numpy(dtype=float)
    return np.column_stack(((r > 0).astype(float), r, np.abs(r), np.maximum(-r, 0)))


def group_moments(groups: np.ndarray, values: np.ndarray):
    encoded = np.where(groups < 0, 8, groups)
    counts = np.bincount(encoded, minlength=9)[:8]
    sums = np.column_stack([np.bincount(encoded, weights=values[:, k], minlength=9)[:8] for k in range(4)])
    means = np.full((8, 4), np.nan)
    np.divide(sums, counts[:, None], out=means, where=counts[:, None] > 0)
    losses = np.bincount(encoded, weights=(values[:, 1] < 0).astype(float), minlength=9)[:8].astype(int)
    conditional_loss = np.full(8, np.nan)
    np.divide(sums[:, 3], losses, out=conditional_loss, where=losses > 0)
    return counts, means, losses, conditional_loss


def block_draws(n: int, batch: int, rng, spec: ConditionSpec = SPEC) -> np.ndarray:
    if n < spec.block_days:
        raise ValueError("phase is shorter than a bootstrap block")
    starts = rng.integers(0, n-spec.block_days+1, size=(batch, math.ceil(n/spec.block_days)))
    return (starts[:, :, None]+np.arange(spec.block_days)).reshape(batch, -1)[:, :n]


def bootstrap_groups(groups: np.ndarray, values: np.ndarray, seed: int, spec: ConditionSpec = SPEC) -> np.ndarray:
    """Resample the entire timeline; group and next-day outcome always travel together."""
    rng = np.random.default_rng(seed)
    n = len(groups)
    encoded = np.where(groups < 0, 8, groups)
    all_means = []
    for start in range(0, spec.bootstrap_samples, spec.bootstrap_batch):
        batch = min(spec.bootstrap_batch, spec.bootstrap_samples-start)
        indexes = block_draws(n, batch, rng, spec)
        cells = encoded[indexes] + np.arange(batch)[:, None]*9
        counts = np.bincount(cells.ravel(), minlength=batch*9).reshape(batch, 9)[:, :8]
        means = np.full((batch, 8, 4), np.nan)
        for k in range(4):
            sums = np.bincount(cells.ravel(), weights=values[indexes, k].ravel(), minlength=batch*9).reshape(batch, 9)[:, :8]
            np.divide(sums, counts, out=means[:, :, k], where=counts > 0)
        all_means.append(means)
    return np.concatenate(all_means)


def finite_interval(draws: np.ndarray) -> tuple[list[float] | None, float]:
    valid = draws[np.isfinite(draws)]
    return (np.quantile(valid, [.025, .975]).tolist() if len(valid) else None), len(valid)/len(draws)


def centered_bootstrap_p(effect: float, draws: np.ndarray) -> float:
    valid = draws[np.isfinite(draws)]
    if not np.isfinite(effect) or not len(valid):
        return 1.0
    return float((1+np.count_nonzero(np.abs(valid-effect) >= abs(effect)))/(1+len(valid)))


def holm_adjust(p_values: np.ndarray) -> np.ndarray:
    if not np.isfinite(p_values).all() or ((p_values < 0) | (p_values > 1)).any():
        raise ValueError("invalid p value")
    order = np.argsort(p_values, kind="stable")
    adjusted_sorted = np.minimum(1, np.maximum.accumulate(p_values[order]*(len(p_values)-np.arange(len(p_values)))))
    adjusted = np.empty(len(p_values))
    adjusted[order] = adjusted_sorted
    return adjusted


def group_label(group: int) -> dict:
    return {"trend": "up" if group//4 else "down", "volatility": "high" if (group//2)%2 else "low", "activity": "high" if group%2 else "low"}


def phase_statistics(part: pd.DataFrame, code: str, phase: str, seed: int, spec: ConditionSpec = SPEC):
    group_rows, comparison_rows, coverage_rows = [], [], []
    values = outcomes(part)
    for view in VIEWS:
        groups = part[f"{view}_group"].to_numpy(dtype=int)
        counts, means, losses, conditional_loss = group_moments(groups, values)
        draws = bootstrap_groups(groups, values, seed, spec)
        coverage_rows.append({
            "ts_code": code, "phase": phase, "view": view, "total": len(part),
            "included": int((groups >= 0).sum()),
            "middle_activity": int((part[f"{view}_exclusion"] == "middle_activity").sum()),
            "flat_r5": int((part[f"{view}_exclusion"] == "flat_r5").sum()),
        })
        for group in range(8):
            row = {"ts_code": code, "phase": phase, "view": view, "group": group,
                   **group_label(group), "n": int(counts[group]), "coverage": counts[group]/len(part),
                   "negative_days": int(losses[group]),
                   "mean_loss_on_negative_days": float(conditional_loss[group]) if losses[group] else None,
                   "enough_samples": bool(counts[group] >= spec.minimum_group_size)}
            for k, metric in enumerate(spec.metrics):
                interval, valid_fraction = finite_interval(draws[:, group, k])
                row[metric] = float(means[group, k]) if counts[group] else None
                row[f"{metric}_ci95_low"] = interval[0] if interval else None
                row[f"{metric}_ci95_high"] = interval[1] if interval else None
                row[f"{metric}_valid_fraction"] = valid_fraction
            group_rows.append(row)
        for low_group in range(0, 8, 2):
            high_group = low_group+1
            for metric in spec.tested_metrics:
                k = spec.metrics.index(metric)
                difference = means[high_group, k]-means[low_group, k]
                differences = draws[:, high_group, k]-draws[:, low_group, k]
                interval, valid_fraction = finite_interval(differences)
                comparison_rows.append({
                    "ts_code": code, "phase": phase, "view": view,
                    "trend": group_label(low_group)["trend"],
                    "volatility": group_label(low_group)["volatility"], "metric": metric,
                    "n_low": int(counts[low_group]), "n_high": int(counts[high_group]),
                    "effect_high_minus_low": float(difference) if np.isfinite(difference) else None,
                    "ci95_low": interval[0] if interval else None,
                    "ci95_high": interval[1] if interval else None,
                    "bootstrap_valid_fraction": valid_fraction,
                    "p_approximate": centered_bootstrap_p(difference, differences),
                    "holm_p": None,
                })
    return group_rows, comparison_rows, coverage_rows


def candidate_decision(rows: list[dict], spec: ConditionSpec = SPEC) -> dict:
    rows = sorted(rows, key=lambda r: spec.phases.index(r["phase"]))
    if len(rows) != 3 or [r["phase"] for r in rows] != list(spec.phases):
        raise ValueError("candidate must have exactly the three time phases")
    enough = all(min(r["n_low"], r["n_high"]) >= spec.minimum_group_size for r in rows)
    valid = all(r["bootstrap_valid_fraction"] >= spec.minimum_valid_bootstrap for r in rows)
    effects = [r["effect_high_minus_low"] for r in rows]
    same_direction = all(v is not None and v > 0 for v in effects) or all(v is not None and v < 0 for v in effects)
    significant_validation = all(r["holm_p"] is not None and r["holm_p"] <= spec.alpha for r in rows[1:])
    return {
        "enough_samples_all_phases": enough, "bootstrap_valid_all_phases": valid,
        "same_direction_all_phases": same_direction,
        "validation_holm_pass_both": significant_validation,
        "candidate": enough and valid and same_direction and significant_validation,
        "effects_D_V1_V2": effects,
    }


def adjust_and_screen(comparisons: list[dict], spec: ConditionSpec = SPEC):
    family = [r for r in comparisons if r["view"] == "amount" and r["phase"] != "D"]
    if len(family) != spec.family_size:
        raise ValueError("Holm family must contain all 48 predeclared validation comparisons")
    p_values = np.asarray([
        r["p_approximate"] if min(r["n_low"], r["n_high"]) >= spec.minimum_group_size
        and r["bootstrap_valid_fraction"] >= spec.minimum_valid_bootstrap else 1.0 for r in family
    ])
    for row, adjusted in zip(family, holm_adjust(p_values), strict=True):
        row["holm_p"] = float(adjusted)
    decisions = []
    for code in first.SPEC.codes:
        for trend in ("down", "up"):
            for volatility in ("low", "high"):
                for metric in spec.tested_metrics:
                    relevant = [r for r in comparisons if r["ts_code"] == code and r["view"] == "amount"
                                and r["trend"] == trend and r["volatility"] == volatility and r["metric"] == metric]
                    decisions.append({"ts_code": code, "trend": trend, "volatility": volatility, "metric": metric,
                                      **candidate_decision(relevant, spec)})
    return decisions


def source_versions_unchanged(manifest: list[dict], earlier: list[dict]) -> None:
    prior_by_path = {r["path"]: r for r in earlier}
    for row in manifest:
        if prior_by_path.get(row["path"]) != row:
            raise ValueError(f"source version differs from the first run: {row['path']}")
        stat = Path(row["path"]).stat()
        if stat.st_size != row["size"] or stat.st_mtime_ns != row["mtime_ns"]:
            raise ValueError(f"source changed during this run: {row['path']}")


def verify_saved_groups(output: Path, group_rows: list[dict]) -> int:
    checked = 0
    with duckdb.connect(":memory:") as connection:
        for view in VIEWS:
            computed = connection.execute(f"""
              SELECT ts_code, phase, {view}_group AS cell, count(*) AS n,
                avg(CAST(next_return>0 AS DOUBLE)) AS up_rate,
                avg(next_return) AS mean_return, avg(abs(next_return)) AS mean_abs_return,
                avg(greatest(-next_return,0)) AS mean_downside,
                count(*) FILTER (WHERE next_return<0) AS negative_days,
                avg(-next_return) FILTER (WHERE next_return<0) AS negative_loss
              FROM read_csv_auto(?) WHERE {view}_group>=0 GROUP BY ts_code,phase,cell
            """, [str(output / "conditional_observations.csv")]).fetchall()
            indexed = {(r["ts_code"], r["phase"], r["group"]): r for r in group_rows if r["view"] == view}
            for code, phase, cell, n, up, ret, absolute, downside, negative_n, negative_loss in computed:
                saved = indexed[(code, phase, cell)]
                if saved["n"] != n or saved["negative_days"] != negative_n:
                    raise RuntimeError("independent SQL group count mismatch")
                for metric, observed in zip(SPEC.metrics, [up, ret, absolute, downside], strict=True):
                    if abs(saved[metric]-observed) > 1e-12:
                        raise RuntimeError("independent SQL group mean mismatch")
                if negative_n and abs(saved["mean_loss_on_negative_days"]-negative_loss) > 1e-12:
                    raise RuntimeError("negative-day denominator mismatch")
                checked += 1
            if sum(r["n"] > 0 for r in indexed.values()) != len(computed):
                raise RuntimeError("group coverage mismatch")
    return checked


def write_report(output: Path, result: dict) -> None:
    decisions = result["screening"]
    direction = sum(r["candidate"] for r in decisions if r["metric"] == "up_rate")
    amplitude = sum(r["candidate"] for r in decisions if r["metric"] == "mean_abs_return")
    rows = ["# 三指数条件统计：第二轮结果", "",
            f"按事前门槛，次日方向跨段候选 **{direction}/12**，次日绝对涨跌幅跨段候选 **{amplitude}/12**。",
            "这里只是原训练期内的探索关联，不是新独立测试、因果证明或可交易的概率模型。首轮预测未证明有效的结论保持不变。",
            "", "## 时间隔离", "",
            "| 阶段 | 信号起日 | 信号末日 | 标签观察至 | 每指数日数 | 边界剔除 |",
            "| --- | --- | --- | --- | ---: | ---: |"]
    for phase in result["phases"]:
        rows.append(f"| {phase['phase']} | {phase['signal_start']} | {phase['signal_end']} | {phase['target_end']} | {phase['actual_per_index']} | {phase['purged_per_index']} |")
    rows += ["", "D确定全部阈值，V1/V2固定使用。没有读取2021-09-08及之后行情。中间成交活跃度不进入8组，但保留覆盖统计；分组阈值是历史分位数，不是固定1倍量额。", "",
             "## 阈值", "", "| 指数 | 低成交额倍数≤ | 高成交额倍数≥ | 高低波动界限（日涨跌幅标准差） |", "| --- | ---: | ---: | ---: |"]
    for code, name in zip(first.SPEC.codes, first.SPEC.names, strict=True):
        threshold = result["thresholds"][code]
        rows.append(f"| {name} | {threshold['amount']['low_ratio']:.3f} | {threshold['amount']['high_ratio']:.3f} | {threshold['sigma20_median']:.2%} |")
    rows += ["", "## 高成交额与低成交额的差异", "",
             "同走势、同波动组内作高−低比较。上涨率差值用百分点，绝对涨跌幅均值差也用百分点；并不是相对增长率。", "",
             "| 指数 | 走势/波动 | 上涨率差 D→V1→V2（百分点） | 波幅差 D→V1→V2（百分点） | 跨段候选 |",
             "| --- | --- | --- | --- | --- |"]
    for code, name in zip(first.SPEC.codes, first.SPEC.names, strict=True):
        for trend in ("down", "up"):
            for volatility in ("low", "high"):
                chosen = [r for r in decisions if r["ts_code"] == code and r["trend"] == trend and r["volatility"] == volatility]
                texts = []
                for metric in SPEC.tested_metrics:
                    item = next(r for r in chosen if r["metric"] == metric)
                    texts.append(" → ".join(f"{v*100:+.2f}" if v is not None else "无样本" for v in item["effects_D_V1_V2"]))
                flags = ["方向" if r["metric"] == "up_rate" else "波幅" for r in chosen if r["candidate"]]
                label = ("上涨" if trend == "up" else "下跌") + "/" + ("高波动" if volatility == "high" else "低波动")
                rows.append(f"| {name} | {label} | {texts[0]} | {texts[1]} | {'、'.join(flags) if flags else '未通过'} |")
    rows += ["", "候选必须三阶段各组n≥50、差值同向，且V1/V2在48项检验共同Holm校正后均p≤0.05；不是看到一格超过50%就算有效。完整计数、95%区间、近似p与Holm值见CSV。", "",
             "## 8组具体表现（成交额视角）", "", "每格为样本数／次日上涨率／平均绝对涨跌幅；低样本组不能作为稳定规律。"]
    for code, name in zip(first.SPEC.codes, first.SPEC.names, strict=True):
        rows += ["", f"### {name}", "", "| 走势/当前波动/成交额活跃度 | D | V1 | V2 |", "| --- | --- | --- | --- |"]
        for group in range(8):
            label = group_label(group)
            label_text = ("涨" if label["trend"] == "up" else "跌") + "/" + ("高波动" if label["volatility"] == "high" else "低波动") + "/" + ("高额" if label["activity"] == "high" else "低额")
            cells = []
            for phase in SPEC.phases:
                item = next(r for r in result["groups"] if r["ts_code"] == code and r["phase"] == phase and r["view"] == "amount" and r["group"] == group)
                cells.append(f"{item['n']}／{item['up_rate']:.1%}／{item['mean_abs_return']:.2%}" if item["n"] else "0／不计算")
            rows.append(f"| {label_text} | {' | '.join(cells)} |")
    rows += ["", "## 当前波动自身的描述对照", "",
             "以下包含各段所有日期，不只高低成交额组。高当前波动后次日波幅更大，即使成立，也不能归功于成交额。", "",
             "| 指数 | D：低/高当前波动后波幅 | V1：低/高 | V2：低/高 |", "| --- | --- | --- | --- |"]
    for code, name in zip(first.SPEC.codes, first.SPEC.names, strict=True):
        cells = []
        for phase in SPEC.phases:
            pair = [r for r in result["volatility_baseline"] if r["ts_code"] == code and r["phase"] == phase]
            values = {r["volatility"]: r["mean_abs_return"] for r in pair}
            cells.append(f"{values['low']:.2%} / {values['high']:.2%}")
        rows.append(f"| {name} | {' | '.join(cells)} |")
    rows += ["", "## 复核与限制", "",
             f"- 数据读取：{result['data']['file_count']}文件，{result['data']['source_rows']}行，{result['data']['total_bytes']/1024**2:.2f}MiB；读取与质量核验{result['data']['read_quality_seconds']:.3f}秒，全轮计算{result['elapsed_seconds']:.3f}秒。",
             f"- 保存的分组明细已用DuckDB独立重算{result['independent_groups_verified']}个非空组的计数、上涨率、平均收益、绝对涨跌幅、下行损失及下跌日条件分母，误差<1e-12。",
             "- 3条批准的前收盘差异保留；其他质量门禁通过。读取范围内源文件与首轮清单一致，执行前后大小和mtime不变。",
             "- 95%组区间用于描述，不能逐格挑显著；筛选用固定48项Holm校正。bootstrap是近似、固定阈值条件下的区间，无法完全处理非平稳和阈值估计误差。",
             "- 成交额高低组内部具体波动与趋势幅度可能不同，不能把分层关联等同于独立预测增益或因果作用。V1/V2仍属于原训练期，后续需要真正未见数据验证。",
             "- 成交量视角只作诊断，不参与赢家筛选；绝对涨跌幅是辅助问题，不能替代次日方向。",
             "- 没有模型调参、没有删除极端日、没有读取原测试期、没有修改DG/Lake/数据库/运行时或安装依赖。",
             "", "## 文件与复现", "",
             "[全部组统计](group_statistics.csv) · [差值与检验](contrasts.csv) · [样本覆盖](coverage.csv) · [分组明细](conditional_observations.csv) · [阈值](thresholds.json) · [完整结果](results.json)",
             "", "```bash", ".venv/bin/python -B -m scripts.research.index_market.statistics.index_condition_statistics --output reports/index_condition_statistics_v1_reproduction", "```"]
    (output / "report.md").write_text("\n".join(rows)+"\n")


def run(output: Path) -> dict:
    start = time.monotonic()
    output = first.safe_output(output)
    prior_metadata = json.loads((PRIOR_RUN / "run_manifest.json").read_text())
    first_script_hash = hashlib.sha256(Path(first.__file__).read_bytes()).hexdigest()
    source_check = verify_prior_source(Path(first.__file__), prior_metadata["script_sha256"])
    output.mkdir(parents=True, exist_ok=False)
    plan = first.PLAN.read_bytes()
    metadata = {"spec": asdict(SPEC), "prior_script_sha256": first_script_hash,
                "prior_source_checks": {Path(first.__file__).name: source_check},
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "plan_sha256_before_run": hashlib.sha256(plan).hexdigest(),
                "stage2_plan_sha256": hashlib.sha256(plan.split(b"## 8.", 1)[1].split(b"## 9.", 1)[0]).hexdigest(),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "versions": {"duckdb": duckdb.__version__, "numpy": np.__version__, "pandas": pd.__version__}}
    first.save_json(output / "run_manifest.json", metadata)
    read_spec = replace(first.SPEC, end=SPEC.source_end, max_files=SPEC.max_files, max_bytes=SPEC.max_bytes, max_rows=SPEC.max_rows)
    print("[1/4] Read only the original training interval; no former test-date files", flush=True)
    connection, data, _ = first.load_lake(read_spec)
    manifest = data.pop("files")
    prior_manifest = json.loads((PRIOR_RUN / "source_manifest.json").read_text())
    try:
        source_versions_unchanged(manifest, prior_manifest)
        features = connection.execute(first.feature_sql()).fetchdf()
    finally:
        connection.close()
    phased, excluded, phases = split_training(features)
    thresholds = fit_thresholds(phased[phased.phase == "D"])
    assigned = assign_groups(phased, thresholds)
    first.save_json(output / "thresholds.json", thresholds)
    first.save_json(output / "source_manifest.json", manifest)
    print(f"[2/4] Phases and D-only thresholds frozen: {json.dumps(phases, ensure_ascii=False)}", flush=True)
    group_rows, contrasts, coverage = [], [], []
    for c, code in enumerate(first.SPEC.codes):
        for p, phase in enumerate(SPEC.phases):
            part = assigned[(assigned.ts_code == code) & (assigned.phase == phase)].sort_values("trade_date")
            groups, comparisons, counts = phase_statistics(part, code, phase, SPEC.seed+c*100+p)
            group_rows.extend(groups)
            contrasts.extend(comparisons)
            coverage.extend(counts)
            print(f"[3/4] {code}/{phase}: {len(part)} dates, two fixed activity views completed", flush=True)
            if time.monotonic()-start > SPEC.max_seconds:
                raise RuntimeError("condition experiment exceeded time budget")
    decisions = adjust_and_screen(contrasts)
    assigned.to_csv(output / "conditional_observations.csv", index=False, float_format="%.17g")
    excluded.to_csv(output / "excluded_boundaries.csv", index=False)
    pd.DataFrame(group_rows).to_csv(output / "group_statistics.csv", index=False)
    pd.DataFrame(contrasts).to_csv(output / "contrasts.csv", index=False)
    pd.DataFrame(coverage).to_csv(output / "coverage.csv", index=False)
    pd.DataFrame(decisions).to_csv(output / "screening.csv", index=False)
    volatility_baseline = []
    for (code, phase, volatility), part in assigned.groupby(["ts_code", "phase", "volatility"]):
        volatility_baseline.append({"ts_code": code, "phase": phase, "volatility": volatility,
                                    "n": len(part), "up_rate": float(part.y.mean()),
                                    "mean_abs_return": float(part.next_return.abs().mean())})
    verified = verify_saved_groups(output, group_rows)
    source_versions_unchanged(manifest, prior_manifest)
    result = {**metadata, "data": data, "phases": phases, "thresholds": thresholds,
              "groups": group_rows, "comparisons": contrasts, "coverage": coverage,
              "screening": decisions, "volatility_baseline": volatility_baseline,
              "source_versions_unchanged": True, "independent_groups_verified": verified,
              "elapsed_seconds": time.monotonic()-start}
    first.save_json(output / "results.json", result)
    write_report(output, result)
    print(f"[4/4] Completed and independently verified: {output / 'report.md'}", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
