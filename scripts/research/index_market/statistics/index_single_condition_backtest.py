"""Third, exploratory experiment: single-condition associations and frozen forecasts."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from scripts.research.index_market.statistics import index_condition_statistics as second
from scripts.research.index_market.statistics import index_probability_backtest as first
from scripts.research.index_market.statistics.provenance import verify_prior_source


@dataclass(frozen=True)
class SingleSpec:
    block_days: int = 20
    bootstrap_samples: int = 10000
    bootstrap_batch: int = 100
    seed: int = 20260908
    minimum_group_size: int = 50
    minimum_valid_bootstrap: float = .99
    family_size: int = 24
    alpha: float = .05
    max_seconds: int = 180


SPEC = SingleSpec()
KINDS = ("direction_gap", "risk_gap", "brier_gain", "mse_gain")
SECOND_RUN = first.REPO / "reports/index_condition_statistics_v1_20260908"


def fit_models(discovery):
    if discovery.empty or set(discovery.phase) != {"D"}:
        raise ValueError("fit requires only D")
    models = {}
    for code in first.SPEC.codes:
        d = discovery[discovery.ts_code == code]
        if d.empty or not np.isfinite(d[["r5", "sigma20", "next_return"]]).all().all():
            raise ValueError("missing or invalid discovery data")
        threshold = float(d.sigma20.median())
        masks = [d.r5 < 0, d.r5 > 0, d.sigma20 <= threshold, d.sigma20 > threshold]
        if any(not mask.any() for mask in masks):
            raise ValueError("empty discovery group")
        models[code] = {
            "fit_start": str(d.trade_date.min().date()), "fit_signal_end": str(d.trade_date.max().date()),
            "fit_target_end": str(d.target_date.max().date()), "n": len(d), "threshold": threshold,
            "p_base": float((d.next_return > 0).mean()), "abs_base": float(d.next_return.abs().mean()),
            "p_down": float((d.loc[masks[0], "next_return"] > 0).mean()),
            "p_up": float((d.loc[masks[1], "next_return"] > 0).mean()),
            "abs_low": float(d.loc[masks[2], "next_return"].abs().mean()),
            "abs_high": float(d.loc[masks[3], "next_return"].abs().mean()),
        }
    return models


def predict(frame, models):
    pieces = []
    if set(frame.ts_code.unique()) - set(models):
        raise ValueError("unknown index")
    for code, d in frame.groupby("ts_code"):
        d = d.copy()
        m = models[code]
        if not np.isfinite(d[["r5", "sigma20"]]).all().all():
            raise ValueError("nonfinite predictor")
        d["direction_group"] = np.where(d.r5 > 0, 1, np.where(d.r5 < 0, 0, -1))
        d["risk_group"] = (d.sigma20 > m["threshold"]).astype(int)
        d["p_base"] = m["p_base"]
        d["p"] = np.where(d.r5 > 0, m["p_up"], np.where(d.r5 < 0, m["p_down"], m["p_base"]))
        d["abs_base"] = m["abs_base"]
        d["abs_pred"] = np.where(d.risk_group == 1, m["abs_high"], m["abs_low"])
        pieces.append(d)
    return pd.concat(pieces, ignore_index=True).sort_values(["ts_code", "trade_date"])


def vectors(part):
    y = (part.next_return.to_numpy() > 0).astype(float)
    absolute = part.next_return.abs().to_numpy()
    return y, absolute, (part.p_base.to_numpy()-y)**2-(part.p.to_numpy()-y)**2, (part.abs_base.to_numpy()-absolute)**2-(part.abs_pred.to_numpy()-absolute)**2


def statistics_at(part, indexes):
    """Each index row is a full paired timeline, not a resampled group alone."""
    values = vectors(part)
    results = []
    for group_field, value in zip(("direction_group", "risk_group"), values[:2], strict=True):
        groups = part[group_field].to_numpy()[indexes]
        sampled = value[indexes]
        means = []
        for g in (0, 1):
            counts = (groups == g).sum(axis=1)
            means.append(np.divide(np.where(groups == g, sampled, 0).sum(axis=1), counts,
                                   out=np.full(len(indexes), np.nan), where=counts > 0))
        results.append(means[1]-means[0])
    results.extend(v[indexes].mean(axis=1) for v in values[2:])
    return np.column_stack(results)


def coverage(frame):
    rows = []
    for (code, phase), part in frame.groupby(["ts_code", "phase"]):
        for view in ("direction", "risk"):
            g = part[f"{view}_group"]
            rows.append({"ts_code": code, "phase": phase, "view": view, "total": len(g),
                         "n0": int((g == 0).sum()), "n1": int((g == 1).sum()), "flat": int((g == -1).sum())})
    return rows


def evaluate_phase(part, seed, spec=SPEC):
    rng = np.random.default_rng(seed)
    draws = np.concatenate([statistics_at(part, second.block_draws(len(part), min(spec.bootstrap_batch, spec.bootstrap_samples-i), rng, spec))
                            for i in range(0, spec.bootstrap_samples, spec.bootstrap_batch)])
    point = statistics_at(part, np.arange(len(part))[None, :])[0]
    tests = []
    for k, kind in enumerate(KINDS):
        group = part["direction_group" if k in (0, 2) else "risk_group"]
        interval, valid = second.finite_interval(draws[:, k])
        tests.append({"ts_code": part.ts_code.iloc[0], "phase": part.phase.iloc[0], "kind": kind,
                      "effect": float(point[k]) if np.isfinite(point[k]) else None, "ci95": interval,
                      "valid_fraction": valid, "min_group": min(int((group == 0).sum()), int((group == 1).sum())),
                      "p_approximate": second.centered_bootstrap_p(point[k], draws[:, k]), "holm_p": None})
    groups = []
    for view in ("direction", "risk"):
        for group, selected in part.groupby(f"{view}_group"):
            if group < 0:
                continue
            groups.append({"ts_code": part.ts_code.iloc[0], "phase": part.phase.iloc[0], "view": view,
                           "group": int(group), "n": len(selected), "up_rate": float((selected.next_return > 0).mean()),
                           "mean_return": float(selected.next_return.mean()), "mean_abs_return": float(selected.next_return.abs().mean())})
    y, absolute, _, _ = vectors(part)
    scores = {"ts_code": part.ts_code.iloc[0], "phase": part.phase.iloc[0], "n": len(part),
              "brier_base": float(np.mean((part.p_base-y)**2)), "brier_model": float(np.mean((part.p-y)**2)),
              "mse_base": float(np.mean((part.abs_base-absolute)**2)), "mse_model": float(np.mean((part.abs_pred-absolute)**2)),
              "accuracy_base": float(np.mean((part.p_base >= .5) == y)), "accuracy_model": float(np.mean((part.p >= .5) == y))}
    for metric in ("brier", "mse"):
        scores[f"{metric}_relative_gain"] = 1-scores[f"{metric}_model"]/scores[f"{metric}_base"] if scores[f"{metric}_base"] else None
    return tests, groups, scores


def screen(tests, spec=SPEC):
    family = [t for t in tests if t["phase"] != "D"]
    if len(family) != spec.family_size or len({(t["ts_code"], t["phase"], t["kind"]) for t in family}) != spec.family_size:
        raise ValueError("expected exact 24 unique validation tests")
    adjusted = second.holm_adjust(np.array([t["p_approximate"] if t["min_group"] >= spec.minimum_group_size
                                          and t["valid_fraction"] >= spec.minimum_valid_bootstrap else 1. for t in family]))
    for t, p in zip(family, adjusted, strict=True):
        t["holm_p"] = float(p)
    decisions = []
    for code in first.SPEC.codes:
        for view, gap_kind, gain_kind in (("direction", "direction_gap", "brier_gain"), ("risk", "risk_gap", "mse_gain")):
            gaps = [next(t for t in tests if t["ts_code"] == code and t["phase"] == p and t["kind"] == gap_kind) for p in second.SPEC.phases]
            gains = [next(t for t in family if t["ts_code"] == code and t["phase"] == p and t["kind"] == gain_kind) for p in ("V1", "V2")]
            effects = [g["effect"] for g in gaps]
            stable = all(e is not None and e > 0 for e in effects) or (view == "direction" and all(e is not None and e < 0 for e in effects))
            enough = all(g["min_group"] >= spec.minimum_group_size for g in gaps)
            valid = all(g["valid_fraction"] >= spec.minimum_valid_bootstrap for g in gaps)
            association = stable and enough and valid and all(g["holm_p"] <= spec.alpha for g in gaps[1:])
            forecast = association and all(g["effect"] is not None and g["effect"] > 0 and g["holm_p"] <= spec.alpha
                                           and g["valid_fraction"] >= spec.minimum_valid_bootstrap for g in gains)
            decisions.append({"ts_code": code, "view": view, "enough_samples": enough, "stable_gap": stable,
                              "association_candidate": association, "forecast_candidate": forecast})
    return decisions


def verify_saved(output, groups, scores):
    with duckdb.connect(":memory:") as con:
        con.execute("CREATE TEMP TABLE saved AS SELECT * FROM read_csv_auto(?)", [str(output / "predictions.csv")])
        checked = 0
        for view in ("direction", "risk"):
            rows = con.execute(f"SELECT ts_code, phase, {view}_group, count(*), avg(CAST(next_return>0 AS DOUBLE)), avg(next_return), avg(abs(next_return)) FROM saved WHERE {view}_group>=0 GROUP BY ALL").fetchall()
            for code, phase, group, n, up, ret, absolute in rows:
                item = next(r for r in groups if (r["ts_code"], r["phase"], r["view"], r["group"]) == (code, phase, view, group))
                assert n == item["n"]
                np.testing.assert_allclose([up, ret, absolute], [item["up_rate"], item["mean_return"], item["mean_abs_return"]], atol=1e-12, rtol=0)
                checked += 1
        assert checked == len(groups)
        rows = con.execute("SELECT ts_code, phase, count(*), avg(pow(p_base-CAST(next_return>0 AS DOUBLE),2)), avg(pow(p-CAST(next_return>0 AS DOUBLE),2)), avg(pow(abs_base-abs(next_return),2)), avg(pow(abs_pred-abs(next_return),2)) FROM saved GROUP BY ALL").fetchall()
        for code, phase, n, *losses in rows:
            item = next(s for s in scores if s["ts_code"] == code and s["phase"] == phase)
            assert n == item["n"]
            np.testing.assert_allclose(losses, [item[k] for k in ("brier_base", "brier_model", "mse_base", "mse_model")], atol=1e-12, rtol=0)
        assert len(rows) == len(scores)
    return {"groups": checked, "scores": len(scores)}


def write_report(output, result):
    rows = ["# 三指数单条件检验：第三轮", "", "仅原训练期内部探索，不能视为新独立测试。D拟合固定值，V1/V2不重训。", "",
            "| 指数 | 方向关联候选 | 方向预测增益 | 风险关联候选 | 风险预测增益 |", "| --- | --- | --- | --- | --- |"]
    for code, name in zip(first.SPEC.codes, first.SPEC.names, strict=True):
        decisions = [next(r for r in result["screening"] if r["ts_code"] == code and r["view"] == v) for v in ("direction", "risk")]
        flags = ["通过内部门槛" if d[k] else "未通过" for d in decisions for k in ("association_candidate", "forecast_candidate")]
        rows.append(f"| {name} | {' | '.join(flags)} |")
    rows += ["", "## 分组表现", "", "方向列为‘近5日下跌/上涨’后次日上涨率；风险列为‘当前低/高波动’后次日平均绝对收益。样本数按相同顺序。", "",
             "| 指数 | 阶段 | 方向样本 | 次日上涨率 | 风险样本 | 次日绝对收益 |", "| --- | --- | --- | --- | --- | --- |"]
    for code, name in zip(first.SPEC.codes, first.SPEC.names, strict=True):
        for phase in second.SPEC.phases:
            cells = []
            for view, metric in (("direction", "up_rate"), ("risk", "mean_abs_return")):
                groups = [next(r for r in result["groups"] if (r["ts_code"], r["phase"], r["view"], r["group"]) == (code, phase, view, g)) for g in (0, 1)]
                cells += [" / ".join(str(g["n"]) for g in groups), " / ".join(f"{g[metric]:.2%}" for g in groups)]
            rows.append(f"| {name} | {phase} | {' | '.join(cells)} |")
    rows += ["", "## 固定预测实际得分", "", "改善率=1−分组误差/基线误差；负数意味着更差。风险MSE单位是小数收益的平方，不是上涨率。", "",
             "| 指数 | 段 | Brier 基线/分组 | 改善率 | 风险MSE 基线/分组 | 改善率 | 方向准确率 基线/分组 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for s in result["scores"]:
        if s["phase"] == "D":
            continue
        rows.append(f"| {s['ts_code']} | {s['phase']} | {s['brier_base']:.6f} / {s['brier_model']:.6f} | {s['brier_relative_gain']:+.2%} | {s['mse_base']:.8f} / {s['mse_model']:.8f} | {s['mse_relative_gain']:+.2%} | {s['accuracy_base']:.2%} / {s['accuracy_model']:.2%} |")
    rows += ["", "## 验证与限制", "",
             f"- 只读{result['data']['file_count']}个文件，{result['data']['source_rows']}行；耗时{result['elapsed_seconds']:.3f}秒。每指数939/939/940日，6条边界剔除，合计8454条预测。",
             f"- DuckDB独立核算{result['verified']['groups']}组均值、{result['verified']['scores']}组预测得分通过；源大小/mtime与旧清单及运行前后相符，3条批准警告保留。未执行DG正式checks或源端重新对账。",
             "- 方向平盘采用D基线预测，所有日期均有预测；分组样本覆盖见coverage.csv。D预测仅为拟合描述，不算验证成绩。",
             "- 95%区间为描述区间；筛选用24项共同Holm校正，详见tests.json。关联要求三段同向及两验证段通过；预测增益还要求两验证段误差改善显著为正。",
             "- 移动块bootstrap是固定阈值和拟合值下的近似推断，不涵盖所有非平稳、参数估计及历史版本修订风险。",
             "- 方案由已见结果启发，本轮校正不消除跨轮选择偏差；三个指数相关，不能算独立复制。即使通过也不能直接宣称可交易或未来有效。风险结果不代替方向结果。",
             "- 本轮不使用量额分组，不评估其增益；没有删极端日、选参、更新旧报告、正式写入、安装或部署。", "",
             "[拟合值](models.json) · [检验与区间](tests.json) · [完整结果](results.json) · [预测明细](predictions.csv)", "",
             "```bash", ".venv/bin/python -B -m scripts.research.index_market.statistics.index_single_condition_backtest --output reports/index_single_condition_reproduction", "```"]
    (output / "report.md").write_text("\n".join(rows)+"\n")


def run(output):
    start = time.monotonic()
    output = first.safe_output(output)
    source_checks = {}
    for module, directory in ((first, second.PRIOR_RUN), (second, SECOND_RUN)):
        recorded = json.loads((directory / "run_manifest.json").read_text())
        source_checks[Path(module.__file__).name] = verify_prior_source(Path(module.__file__), recorded["script_sha256"])
    output.mkdir(parents=True, exist_ok=False)
    plan = first.PLAN.read_bytes()
    metadata = {"spec": asdict(SPEC), "source_and_split_spec": asdict(second.SPEC),
                "prior_source_checks": source_checks,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "prior_script_hashes": {Path(m.__file__).name: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (first, second)},
                "frozen_plan_sha256": hashlib.sha256(plan.split(b"## 10.", 1)[1].split(b"## 11.", 1)[0]).hexdigest(),
                "plan_before_run_sha256": hashlib.sha256(plan).hexdigest(), "created_at": datetime.now(timezone.utc).isoformat(),
                "versions": {"duckdb": duckdb.__version__, "numpy": np.__version__, "pandas": pd.__version__}}
    first.save_json(output / "run_manifest.json", metadata)
    read_spec = replace(first.SPEC, end=second.SPEC.source_end, max_files=second.SPEC.max_files, max_bytes=second.SPEC.max_bytes, max_rows=second.SPEC.max_rows)
    con, data, _ = first.load_lake(read_spec)
    manifest = data.pop("files")
    prior_manifest = json.loads((second.PRIOR_RUN / "source_manifest.json").read_text())
    try:
        second.source_versions_unchanged(manifest, prior_manifest)
        phased, excluded, phases = second.split_training(con.execute(first.feature_sql()).fetchdf())
    finally:
        con.close()
    models = fit_models(phased[phased.phase == "D"])
    predicted = predict(phased, models)
    counts = coverage(predicted)
    first.save_json(output / "coverage.json", counts)
    print("[1/3] Pre-score coverage: " + json.dumps(counts), flush=True)
    first.save_json(output / "models.json", models)
    tests, groups, scores = [], [], []
    for c, code in enumerate(first.SPEC.codes):
        for p, phase in enumerate(second.SPEC.phases):
            part = predicted[(predicted.ts_code == code) & (predicted.phase == phase)].sort_values("trade_date")
            t, g, s = evaluate_phase(part, SPEC.seed+100*c+p)
            tests.extend(t)
            groups.extend(g)
            scores.append(s)
            print(f"[2/3] {code}/{phase}: {len(part)} dates verified", flush=True)
            if time.monotonic()-start > SPEC.max_seconds:
                raise RuntimeError("time budget exceeded")
    decisions = screen(tests)
    predicted.to_csv(output / "predictions.csv", index=False, float_format="%.17g")
    excluded.to_csv(output / "excluded_boundaries.csv", index=False)
    for name, rows in (("groups", groups), ("scores", scores), ("coverage", counts), ("screening", decisions)):
        pd.DataFrame(rows).to_csv(output / f"{name}.csv", index=False)
    verified = verify_saved(output, groups, scores)
    second.source_versions_unchanged(manifest, prior_manifest)
    result = {**metadata, "data": data, "phases": phases, "models": models, "coverage": counts,
              "groups": groups, "scores": scores, "tests": tests, "screening": decisions, "verified": verified,
              "elapsed_seconds": time.monotonic()-start}
    first.save_json(output / "source_manifest.json", manifest)
    first.save_json(output / "tests.json", tests)
    first.save_json(output / "results.json", result)
    write_report(output, result)
    print(f"[3/3] Saved and independently verified {output / 'report.md'}", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
