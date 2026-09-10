"""Frozen fourth experiment: the unchanged risk model versus a rolling baseline."""
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
from scripts.research.index_market.statistics import index_single_condition_backtest as third
from scripts.research.index_market.statistics.provenance import verify_prior_source


@dataclass(frozen=True)
class RiskSpec:
    window: int = 20
    block_days: int = 20
    bootstrap_samples: int = 10000
    bootstrap_batch: int = 100
    family_size: int = 6
    minimum_days: int = 50
    seed: int = 20260908
    alpha: float = .05
    max_seconds: int = 180


SPEC = RiskSpec()
PRIOR = first.REPO / "reports/index_single_condition_v1_20260908"
METHODS = {"constant": "abs_base", "fixed_group": "abs_pred", "rolling20": "abs20"}


def risk_feature_sql(spec=SPEC):
    if spec.window != 20:
        raise ValueError("this experiment only allows the frozen 20-day window")
    return f"""WITH original AS ({first.feature_sql()})
      SELECT *, CASE WHEN count(r1) OVER w = 20 THEN avg(abs(r1)) OVER w END AS abs20,
        count(r1) OVER w AS abs20_count
      FROM original WINDOW w AS (
        PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
      ORDER BY ts_code, trade_date"""


def verify_rolling(features):
    expected = features.groupby("ts_code", sort=False).r1.transform(lambda r: r.abs().rolling(20, min_periods=20).mean())
    np.testing.assert_allclose(features.abs20, expected, atol=1e-12, rtol=0, equal_nan=True)


def require_complete_windows(frame):
    if not frame.abs20_count.eq(20).all() or not np.isfinite(frame.abs20).all() or (frame.abs20 < 0).any():
        raise ValueError("eligible dates require 20 finite trailing daily returns")


def score_phase(part):
    y = part.next_return.abs().to_numpy()
    rows = []
    for method, field in METHODS.items():
        pred = part[field].to_numpy()
        if not np.isfinite(pred).all() or not np.isfinite(y).all() or (pred < 0).any():
            raise ValueError("invalid prediction or target")
        error = pred-y
        rows.append({"ts_code": part.ts_code.iloc[0], "phase": part.phase.iloc[0], "method": method,
                     "n": len(part), "mse": float(np.mean(error**2)), "mae": float(np.mean(np.abs(error))),
                     "mean_prediction": float(pred.mean()), "mean_observed": float(y.mean())})
    return rows


def compare(part, seed, spec=SPEC):
    if len(part) < spec.minimum_days:
        raise ValueError("too few paired dates")
    y = part.next_return.abs().to_numpy()
    rolling_loss = (part.abs20.to_numpy()-y)**2
    fixed_loss = (part.abs_pred.to_numpy()-y)**2
    delta = rolling_loss-fixed_loss
    if not np.isfinite(delta).all():
        raise ValueError("nonfinite paired losses")
    rng = np.random.default_rng(seed)
    draws = np.concatenate([delta[second.block_draws(len(part), min(spec.bootstrap_batch, spec.bootstrap_samples-i), rng, spec)].mean(axis=1)
                            for i in range(0, spec.bootstrap_samples, spec.bootstrap_batch)])
    effect = float(delta.mean())
    return {"ts_code": part.ts_code.iloc[0], "phase": part.phase.iloc[0], "n": len(part),
            "effect_rolling_minus_fixed": effect, "ci95": np.quantile(draws, [.025, .975]).tolist(),
            "fixed_relative_gain": float(effect/rolling_loss.mean()) if rolling_loss.mean() else None,
            "rolling_relative_gain": float(-effect/fixed_loss.mean()) if fixed_loss.mean() else None,
            "p_approximate": second.centered_bootstrap_p(effect, draws), "holm_p": None}


def classify(comparisons, spec=SPEC):
    expected = {(c, p) for c in first.SPEC.codes for p in ("V1", "V2")}
    if len(comparisons) != spec.family_size or {(r["ts_code"], r["phase"]) for r in comparisons} != expected:
        raise ValueError("exact six validation comparisons required")
    ps = np.array([r["p_approximate"] if r["n"] >= spec.minimum_days else 1. for r in comparisons])
    for row, p in zip(comparisons, second.holm_adjust(ps), strict=True):
        row["holm_p"] = float(p)
    decisions = []
    for code in first.SPEC.codes:
        pair = [r for r in comparisons if r["ts_code"] == code]
        significant = all(r["holm_p"] <= spec.alpha and r["n"] >= spec.minimum_days for r in pair)
        fixed = significant and all(r["effect_rolling_minus_fixed"] > 0 for r in pair)
        rolling = significant and all(r["effect_rolling_minus_fixed"] < 0 for r in pair)
        decisions.append({"ts_code": code, "verdict": "fixed_better" if fixed else "rolling_better" if rolling else "no_cross_phase_evidence"})
    return decisions


def verify_saved(output, scores):
    with duckdb.connect(":memory:") as con:
        con.execute("CREATE TEMP TABLE p AS SELECT * FROM read_csv_auto(?)", [str(output / "predictions.csv")])
        checked = 0
        for method, field in METHODS.items():
            rows = con.execute(f"SELECT ts_code,phase,count(*),avg(pow({field}-abs(next_return),2)),avg(abs({field}-abs(next_return))) FROM p GROUP BY ALL").fetchall()
            for code, phase, n, mse, mae in rows:
                row = next(s for s in scores if (s["ts_code"], s["phase"], s["method"]) == (code, phase, method))
                assert n == row["n"]
                np.testing.assert_allclose([mse, mae], [row["mse"], row["mae"]], atol=1e-12, rtol=0)
                checked += 1
        assert checked == len(scores)
    return checked


def verify_prior_predictions(predicted, prior):
    keys = ["ts_code", "trade_date"]
    current = predicted.sort_values(keys).reset_index(drop=True)
    old = prior.sort_values(keys).reset_index(drop=True)
    pd.testing.assert_frame_equal(current[keys], old[keys])
    for field in ("abs_base", "abs_pred", "next_return"):
        np.testing.assert_allclose(current[field], old[field], atol=1e-12, rtol=0)


def write_report(output, result):
    labels = {"fixed_better": "固定模型胜出", "rolling_better": "动态基线胜出", "no_cross_phase_evidence": "未证明跨段优势"}
    rows = ["# 风险模型对动态基线：第四轮", "", "原训练期内重复使用历史数据的内部比较；不是新的独立验证。", "",
            "| 指数 | V1动态相对固定的MSE改善 | V2动态相对固定的MSE改善 | 跨段判断 |", "| --- | ---: | ---: | --- |"]
    for code, name in zip(first.SPEC.codes, first.SPEC.names, strict=True):
        cs = [next(c for c in result["comparisons"] if c["ts_code"] == code and c["phase"] == p) for p in ("V1", "V2")]
        verdict = next(d["verdict"] for d in result["decisions"] if d["ts_code"] == code)
        rows.append(f"| {name} | {cs[0]['rolling_relative_gain']:+.2%} | {cs[1]['rolling_relative_gain']:+.2%} | {labels[verdict]} |")
    rows += ["", "改善=1−动态MSE/固定模型MSE；正数代表动态基线更好。不是命中率、收益率或下降百分点。", "",
             "## 原始得分", "", "MSE使用小数收益平方；MAE为小数收益绝对误差，辅助展示不用于挑赢家。", "",
             "| 指数 | 阶段 | 方法 | 日数 | MSE | MAE |", "| --- | --- | --- | ---: | ---: | ---: |"]
    for s in result["scores"]:
        if s["phase"] != "D":
            rows.append(f"| {s['ts_code']} | {s['phase']} | {s['method']} | {s['n']} | {s['mse']:.8f} | {s['mae']:.6f} |")
    rows += ["", "## 六项比较及不确定性", "", "差值=动态MSE−固定MSE，负数为动态更好；95%区间为描述，判定用六项Holm校正。", "",
             "| 指数 | 段 | 差值 | 95%区间 | 校正p |", "| --- | --- | --- | --- | --- |"]
    for c in result["comparisons"]:
        rows.append(f"| {c['ts_code']} | {c['phase']} | {c['effect_rolling_minus_fixed']:.8f} | [{c['ci95'][0]:.8f}, {c['ci95'][1]:.8f}] | {c['holm_p']:.5f} |")
    rows += ["", "## 口径与复核", "",
             "- 固定模型直接消费第三轮D拟合值；动态基线为截至当天最近20个日收益绝对值的均值，用于预测次日绝对收益。先完整序列滚动再切分，不丢窗口内的已知边界日。",
             "- D信号2010-02-01—2013-12-19；V1为2013-12-23—2017-10-27；V2为2017-10-31—2021-09-06。标签分别至2013-12-20、2017-10-30、2021-09-07。没有读取原测试期行情。",
             f"- 只读{result['data']['file_count']}文件/{result['data']['source_rows']}行，{result['data']['total_bytes']/1024**2:.2f}MiB；总耗时{result['elapsed_seconds']:.3f}秒。8454条预测、6条边界剔除。",
             f"- 完整序列的20日窗口经Pandas独立核算；所有固定预测及9组旧MSE与第三轮一致；保存后DuckDB独立核算{result['verified_score_groups']}组MSE/MAE。源文件清单及前后大小/mtime一致，源数据摘要与第三轮一致。",
             "- 前三轮脚本哈希核验通过，3条批准前收盘警告保留；未执行DG正式checks、源端重新对账、正式写入、部署、安装或提交。",
             "- 20日块/10000次配对bootstrap仅缓解时间相关；历史非平稳、跨轮选择、历史版本修订仍有限制。本轮Holm只覆盖六项比较，三个相关指数不是独立复制。",
             "- 本轮不搜索窗口、不混合模型或动态重拟合分组；任何胜出不能说明会涨还是会跌，也不支持直接给交易建议。", "",
             "[完整结果](results.json) · [预测明细](predictions.csv) · [得分](scores.csv) · [拟合值](models.json)", "",
             "```bash", ".venv/bin/python -B -m scripts.research.index_market.statistics.index_risk_baseline_backtest --output reports/index_risk_baseline_reproduction", "```"]
    (output / "report.md").write_text("\n".join(rows)+"\n")


def run(output):
    start = time.monotonic()
    output = first.safe_output(output)
    old_hashes = {}
    source_checks = {}
    for module, directory in ((first, second.PRIOR_RUN), (second, third.SECOND_RUN), (third, PRIOR)):
        digest = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        source_checks[Path(module.__file__).name] = verify_prior_source(
            Path(module.__file__), json.loads((directory / "run_manifest.json").read_text())["script_sha256"])
        old_hashes[Path(module.__file__).name] = digest
    output.mkdir(parents=True, exist_ok=False)
    plan = first.PLAN.read_bytes()
    metadata = {"spec": asdict(SPEC), "source_and_split_spec": asdict(second.SPEC), "prior_script_hashes": old_hashes,
                "prior_source_checks": source_checks,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "frozen_plan_sha256": hashlib.sha256(plan.split(b"## 12.", 1)[1].split(b"## 13.", 1)[0]).hexdigest(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "versions": {"duckdb": duckdb.__version__, "numpy": np.__version__, "pandas": pd.__version__}}
    first.save_json(output / "run_manifest.json", metadata)
    read_spec = replace(first.SPEC, end=second.SPEC.source_end, max_files=second.SPEC.max_files, max_bytes=second.SPEC.max_bytes, max_rows=second.SPEC.max_rows)
    print("[1/3] Read original training interval and verify continuous 20-day windows", flush=True)
    con, data, _ = first.load_lake(read_spec)
    manifest = data.pop("files")
    earlier_manifest = json.loads((second.PRIOR_RUN / "source_manifest.json").read_text())
    try:
        second.source_versions_unchanged(manifest, earlier_manifest)
        features = con.execute(risk_feature_sql()).fetchdf()
    finally:
        con.close()
    verify_rolling(features)
    phased, excluded, phases = second.split_training(features)
    require_complete_windows(phased)
    models = json.loads((PRIOR / "models.json").read_text())
    if third.fit_models(phased[phased.phase == "D"]) != models:
        raise ValueError("third-round fit changed")
    prior_result = json.loads((PRIOR / "results.json").read_text())
    if data["canonical_selected_input_sha256"] != prior_result["data"]["canonical_selected_input_sha256"]:
        raise ValueError("source data digest changed")
    predicted = third.predict(phased, models)
    old_predictions = pd.read_csv(PRIOR / "predictions.csv", parse_dates=["trade_date"])
    verify_prior_predictions(predicted, old_predictions)
    scores, comparisons = [], []
    for c, code in enumerate(first.SPEC.codes):
        for p, phase in enumerate(second.SPEC.phases):
            part = predicted[(predicted.ts_code == code) & (predicted.phase == phase)].sort_values("trade_date")
            scored = score_phase(part)
            old = next(s for s in prior_result["scores"] if s["ts_code"] == code and s["phase"] == phase)
            np.testing.assert_allclose(scored[1]["mse"], old["mse_model"], atol=1e-12, rtol=0)
            scores.extend(scored)
            if phase != "D":
                comparisons.append(compare(part, SPEC.seed+100*c+p))
                print(f"[2/3] {code}/{phase}: {len(part)} paired dates", flush=True)
            if time.monotonic()-start > SPEC.max_seconds:
                raise RuntimeError("time budget exceeded")
    decisions = classify(comparisons)
    keep = ["ts_code", "trade_date", "target_date", "phase", "r1", "sigma20", "risk_group", "next_return", "abs_base", "abs_pred", "abs20", "abs20_count"]
    predicted[keep].to_csv(output / "predictions.csv", index=False, float_format="%.17g")
    excluded.to_csv(output / "excluded_boundaries.csv", index=False)
    pd.DataFrame(scores).to_csv(output / "scores.csv", index=False)
    verified = verify_saved(output, scores)
    second.source_versions_unchanged(manifest, earlier_manifest)
    result = {**metadata, "data": data, "phases": phases, "scores": scores, "comparisons": comparisons,
              "decisions": decisions, "verified_score_groups": verified, "elapsed_seconds": time.monotonic()-start}
    for filename, value in (("models.json", models), ("source_manifest.json", manifest), ("results.json", result)):
        first.save_json(output / filename, value)
    write_report(output, result)
    print(f"[3/3] Completed {output / 'report.md'}", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
