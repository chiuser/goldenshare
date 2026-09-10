"""Versioned, read-only index probability experiment; not a production entrypoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Spec:
    experiment_id: str = "index-next-day-probability-v1"
    codes: tuple[str, ...] = ("000001.SH", "000300.SH", "000905.SH")
    names: tuple[str, ...] = ("上证指数", "沪深300", "中证500")
    start: str = "2010-01-04"
    end: str = "2026-09-07"
    train_fraction: float = 0.70
    ridge: float = 0.01
    max_iterations: int = 100
    gradient_tolerance: float = 1e-8
    block_days: int = 20
    bootstrap_samples: int = 5000
    seed: int = 20260908
    family_comparisons: int = 6
    max_files: int = 6000
    max_bytes: int = 512 * 1024**2
    max_rows: int = 18000
    max_seconds: int = 120
    price_tolerance: float = 0.001
    pct_tolerance: float = 0.001
    approved_pre_close_warnings: tuple[tuple[str, str, float, float], ...] = (
        ("000001.SH", "2011-03-01", 2905.197, 2905.053),
        ("000001.SH", "2014-06-30", 2036.408, 2036.510),
        ("000300.SH", "2010-01-26", 3325.691, 3328.014),
    )
    price_features: tuple[str, ...] = ("r1", "r5", "r20", "sigma20")
    amount_features: tuple[str, ...] = ("a20", "r5_a20")
    volume_features: tuple[str, ...] = ("v20", "r5_v20")


SPEC = Spec()
REPO = Path(__file__).resolve().parents[4]
LAKE = Path("/Volumes/datasource/data_lake")
PLAN = REPO / "docs/product/index-next-day-probability-backtest-plan-v1.md"


def model_features(spec: Spec = SPEC) -> dict[str, tuple[str, ...]]:
    return {
        "price": spec.price_features,
        "price_amount": spec.price_features + spec.amount_features,
        "price_amount_volume": (
            spec.price_features + spec.amount_features + spec.volume_features
        ),
    }


def sigmoid(z: np.ndarray) -> np.ndarray:
    return np.exp(-np.logaddexp(0.0, -z))


def objective_gradient_hessian(
    design: np.ndarray, y: np.ndarray, beta: np.ndarray, ridge: float
) -> tuple[float, np.ndarray, np.ndarray]:
    z = design @ beta
    p = sigmoid(z)
    penalty = np.full(len(beta), ridge)
    penalty[0] = 0.0
    objective = np.mean(np.logaddexp(0.0, z) - y * z)
    objective += 0.5 * np.dot(penalty, beta * beta)
    gradient = design.T @ (p - y) / len(y) + penalty * beta
    hessian = (design.T * (p * (1.0 - p))) @ design / len(y)
    hessian += np.diag(penalty)
    return float(objective), gradient, hessian


def fit_logistic(x: np.ndarray, y: np.ndarray, spec: Spec = SPEC) -> dict:
    if len(np.unique(y)) != 2 or not np.isfinite(x).all():
        raise ValueError("training requires finite features and both outcome classes")
    mean = x.mean(axis=0)
    scale = x.std(axis=0, ddof=0)
    scale = np.where(scale == 0.0, 1.0, scale)
    design = np.column_stack((np.ones(len(x)), (x - mean) / scale))
    beta = np.zeros(design.shape[1])
    beta[0] = math.log(y.mean() / (1.0 - y.mean()))
    for iteration in range(spec.max_iterations):
        loss, gradient, hessian = objective_gradient_hessian(design, y, beta, spec.ridge)
        norm = float(np.max(np.abs(gradient)))
        if norm <= spec.gradient_tolerance:
            return {
                "mean": mean.tolist(), "scale": scale.tolist(),
                "beta": beta.tolist(), "iterations": iteration,
                "gradient_inf_norm": norm, "objective": loss,
            }
        direction = np.linalg.solve(hessian, gradient)
        step = 1.0
        for _ in range(40):
            candidate = beta - step * direction
            next_loss, _, _ = objective_gradient_hessian(design, y, candidate, spec.ridge)
            if next_loss <= loss - 1e-4 * step * float(gradient @ direction):
                beta = candidate
                break
            step *= 0.5
        else:
            raise RuntimeError("logistic line search failed")
    raise RuntimeError("logistic model did not converge; no test score produced")


def predict_logistic(model: dict, x: np.ndarray) -> np.ndarray:
    z = (x - np.asarray(model["mean"])) / np.asarray(model["scale"])
    beta = np.asarray(model["beta"])
    return sigmoid(beta[0] + z @ beta[1:])


def feature_sql(table: str = "observations") -> str:
    if table != "observations":
        raise ValueError("only the isolated observations table is supported")
    return """
    WITH returns AS (
      SELECT ts_code, trade_date, close, amount, vol,
        close / lag(close, 1) OVER w - 1 AS r1,
        close / lag(close, 5) OVER w - 1 AS r5,
        close / lag(close, 20) OVER w - 1 AS r20,
        median(amount) OVER (
          PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS previous_amount_median,
        median(vol) OVER (
          PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS previous_volume_median,
        lead(trade_date) OVER w AS target_date,
        lead(close) OVER w / close - 1 AS next_return
      FROM observations
      WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date)
    ), features AS (
      SELECT *, stddev_samp(r1) OVER (
        PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
      ) AS sigma20,
      ln(amount / previous_amount_median) AS a20,
      ln(vol / previous_volume_median) AS v20
      FROM returns
    )
    SELECT ts_code, trade_date, target_date, r1, r5, r20, sigma20, a20, v20,
      r5*a20 AS r5_a20, r5*v20 AS r5_v20, next_return,
      CASE WHEN next_return IS NULL THEN NULL WHEN next_return > 0 THEN 1 ELSE 0 END AS y
    FROM features ORDER BY ts_code, trade_date
    """


def validate_observations(frame: pd.DataFrame, calendar: pd.DataFrame, spec: Spec = SPEC) -> dict:
    if len(frame) > spec.max_rows or set(frame.ts_code.unique()) != set(spec.codes):
        raise ValueError("row budget or exact three-index scope failed")
    if frame.duplicated(["ts_code", "trade_date"]).any():
        raise ValueError("duplicate index/date")
    if calendar.trade_date.duplicated().any() or calendar.empty:
        raise ValueError("duplicate or empty SSE open-day calendar")
    required = ["open", "high", "low", "close", "pre_close", "vol", "amount"]
    values = frame[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("null, nonfinite or nonpositive market values")
    if not np.isfinite(frame.pct_chg.to_numpy(dtype=float)).all():
        raise ValueError("invalid pct_chg")
    if (frame.high + spec.price_tolerance < frame[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("invalid OHLC high")
    if (frame.low - spec.price_tolerance > frame[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("invalid OHLC low")
    if "partition_date" in frame and not frame.trade_date.equals(frame.partition_date):
        raise ValueError("file date differs from partition date")
    expected = set(pd.to_datetime(calendar.trade_date))
    profiles = {}
    for code in spec.codes:
        part = frame[frame.ts_code == code].sort_values("trade_date")
        actual = set(pd.to_datetime(part.trade_date))
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ValueError(f"calendar mismatch {code}: missing={missing[:5]}, extra={extra[:5]}")
        prior_close = part.close.shift(1)
        close_gap = (part.pre_close - prior_close).abs().dropna()
        pct_gap = (part.pct_chg - 100.0*(part.close / part.pre_close - 1.0)).abs()
        if (pct_gap > spec.pct_tolerance).any():
            raise ValueError(f"pct units mismatch: {code}")
        warnings = []
        allowed = {(c, d): (pre, prior) for c, d, pre, prior in spec.approved_pre_close_warnings}
        for index in close_gap[close_gap > spec.price_tolerance].index:
            day = str(part.loc[index, "trade_date"].date())
            observed = (float(part.loc[index, "pre_close"]), float(prior_close.loc[index]))
            expected_pair = allowed.get((code, day))
            if expected_pair is None or not np.allclose(observed, expected_pair, rtol=0, atol=1e-8):
                raise ValueError(f"unapproved pre_close discontinuity: {code}/{day}")
            warnings.append({
                "trade_date": day, "pre_close": observed[0], "prior_close": observed[1],
                "absolute_gap": float(close_gap.loc[index]),
                "action": "retained; close-to-close features and target unchanged; user-approved warning",
            })
        profiles[code] = {
            "rows": len(part), "first": str(part.trade_date.min().date()),
            "last": str(part.trade_date.max().date()), "missing_dates": 0,
            "duplicate_keys": 0, "invalid_market_values": 0,
            "max_pre_close_gap": float(close_gap.max()),
            "approved_pre_close_warnings": warnings,
            "max_pct_chg_gap_percentage_points": float(pct_gap.max()),
        }
    return profiles


def split_features(features: pd.DataFrame, spec: Spec = SPEC) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    cols = list(model_features(spec)["price_amount_volume"])
    valid = features.dropna(subset=cols + ["target_date", "y"]).copy()
    if not np.isfinite(valid[cols].to_numpy(dtype=float)).all():
        raise ValueError("nonfinite computed features")
    date_sets = [set(valid[valid.ts_code == code].trade_date) for code in spec.codes]
    if not date_sets or any(dates != date_sets[0] for dates in date_sets):
        raise ValueError("eligible signal dates differ between indices")
    dates = sorted(date_sets[0])
    if len(dates) < 1000:
        raise ValueError("insufficient history for this frozen experiment")
    cut = int(len(dates) * spec.train_fraction)
    test_start = dates[cut]
    training_before_purge = valid[valid.trade_date < test_start]
    train = training_before_purge[training_before_purge.target_date < test_start].copy()
    test = valid[valid.trade_date >= test_start].copy()
    audit = {
        "eligible_per_index": len(dates), "nominal_train_per_index": cut,
        "train_per_index": len(train) // len(spec.codes),
        "purged_per_index": (len(training_before_purge)-len(train)) // len(spec.codes),
        "test_per_index": len(test) // len(spec.codes),
        "train_start": str(train.trade_date.min().date()),
        "train_signal_end": str(train.trade_date.max().date()),
        "train_target_end": str(train.target_date.max().date()),
        "test_signal_start": str(test.trade_date.min().date()),
        "test_signal_end": str(test.trade_date.max().date()),
        "test_target_start": str(test.target_date.min().date()),
        "test_target_end": str(test.target_date.max().date()),
        "warmup_excluded_per_index": int(features[features.ts_code == spec.codes[0]][cols].isna().any(axis=1).sum()),
        "last_unlabelled_per_index": int(features[features.ts_code == spec.codes[0]].y.isna().sum()),
    }
    assert train.target_date.max() < test.trade_date.min()
    return train, test, audit


def score(y: np.ndarray, p: np.ndarray) -> dict:
    if len(y) == 0 or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("invalid probability vector")
    positives = int(y.sum())
    negatives = len(y) - positives
    ranks = pd.Series(p).rank(method="average").to_numpy()
    auc = None
    if positives and negatives:
        auc = float((ranks[y == 1].sum() - positives*(positives+1)/2) / (positives*negatives))
    clipped = np.clip(p, 1e-15, 1.0-1e-15)
    return {
        "n": len(y), "brier": float(np.mean((p-y)**2)),
        "log_loss": float(-np.mean(y*np.log(clipped)+(1-y)*np.log1p(-clipped))),
        "accuracy": float(np.mean((p >= 0.5) == y)), "auc": auc,
        "actual_up_rate": float(y.mean()), "mean_probability": float(p.mean()),
        "p_min": float(p.min()), "p_max": float(p.max()),
    }


def bootstrap_comparison(y: np.ndarray, baseline: np.ndarray, candidate: np.ndarray, spec: Spec = SPEC) -> dict:
    difference = (baseline-y)**2 - (candidate-y)**2
    n = len(difference)
    if n < spec.block_days:
        raise ValueError("too few test dates for bootstrap block length")
    rng = np.random.default_rng(spec.seed)
    block_count = math.ceil(n/spec.block_days)
    offsets = np.arange(spec.block_days)
    samples = []
    for start in range(0, spec.bootstrap_samples, 100):
        batch = min(100, spec.bootstrap_samples-start)
        block_starts = rng.integers(0, n-spec.block_days+1, size=(batch, block_count))
        indexes = (block_starts[:, :, None] + offsets).reshape(batch, -1)[:, :n]
        samples.append(difference[indexes].mean(axis=1))
    draws = np.concatenate(samples)
    adjusted_tail = 0.05/(2*spec.family_comparisons)
    adjusted = np.quantile(draws, [adjusted_tail, 1-adjusted_tail]).tolist()
    return {
        "brier_improvement": float(difference.mean()),
        "ci95": np.quantile(draws, [0.025, 0.975]).tolist(),
        "family_adjusted_ci": adjusted,
        "family_adjusted_confidence": 1-0.05/spec.family_comparisons,
        "positive_after_family_correction": bool(adjusted[0] > 0),
        "method": "paired noncircular moving-block percentile bootstrap",
    }


def safe_output(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(REPO / "reports") or resolved == REPO / "reports":
        raise ValueError("output must be a new child directory under repository reports")
    if resolved.exists():
        raise ValueError("refusing to overwrite an existing report directory")
    return resolved


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def load_lake(spec: Spec = SPEC) -> tuple[duckdb.DuckDBPyConnection, dict, pd.DataFrame]:
    started = time.monotonic()
    paths = sorted(
        path for path in (LAKE / "silver/index_daily").glob("trade_date=*/part-000.parquet")
        if spec.start <= path.parent.name.removeprefix("trade_date=") <= spec.end
    )
    calendar_path = LAKE / "silver/calendar/trade_calendar/full/part-000.parquet"
    paths_all = paths + [calendar_path]
    manifest = [
        {"path": str(path), "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
        for path in paths_all
    ]
    total_bytes = sum(item["size"] for item in manifest)
    if not paths or len(paths_all) > spec.max_files or total_bytes > spec.max_bytes:
        raise ValueError("source file count or byte budget exceeded")
    connection = duckdb.connect(":memory:", config={
        "threads": 4, "memory_limit": "1GB", "max_temp_directory_size": "0B",
        "allow_persistent_secrets": False, "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
    })
    connection.execute("SET allowed_paths = ?", [[str(path) for path in paths_all]])
    connection.execute("SET enable_external_access = false")
    connection.execute("SET lock_configuration = true")
    connection.execute("""
      CREATE TEMP TABLE observations AS
      SELECT ts_code, trade_date, open, high, low, close, pre_close, pct_chg, vol, amount,
        CAST(regexp_extract(filename, 'trade_date=([0-9-]+)', 1) AS DATE) AS partition_date
      FROM read_parquet(?, hive_partitioning=false, filename=true)
      WHERE ts_code IN (SELECT unnest(?))
    """, [[str(path) for path in paths], list(spec.codes)])
    n = connection.execute("SELECT count(*) FROM observations").fetchone()[0]
    if n > spec.max_rows:
        connection.close()
        raise ValueError("filtered source rows exceeded budget")
    frame = connection.execute("SELECT * FROM observations ORDER BY ts_code, trade_date").fetchdf()
    calendar = connection.execute("""
      SELECT trade_date FROM read_parquet(?, hive_partitioning=false)
      WHERE exchange='SSE' AND is_open AND trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
      ORDER BY trade_date
    """, [str(calendar_path), spec.start, spec.end]).fetchdf()
    profiles = validate_observations(frame, calendar, spec)
    digest = hashlib.sha256(frame.to_csv(index=False, float_format="%.17g").encode()).hexdigest()
    evidence = {
        "files": manifest, "file_count": len(paths_all), "total_bytes": total_bytes,
        "source_rows": int(n), "sse_open_days": len(calendar), "profiles": profiles,
        "canonical_selected_input_sha256": digest,
        "input_digest_encoding": "sorted pandas CSV, float_format=%.17g, includes partition date; not persisted",
        "read_quality_seconds": time.monotonic()-started,
        "formal_dagster_checks_executed": False,
        "source_revision_time_travel_available": False,
    }
    return connection, evidence, frame


def write_report(output: Path, results: dict) -> None:
    split = results["split"]
    rows = [
        "# 三指数次日上涨概率回测结果 v1", "",
        "这是固定70%训练／30%测试的预测实验，不是交易收益回测。",
        "",
        f"训练信号：{split['train_start']}—{split['train_signal_end']}；"
        f"测试信号：{split['test_signal_start']}—{split['test_signal_end']}。",
        f"每指数训练 {split['train_per_index']} 日，测试 {split['test_per_index']} 日；"
        f"测试结果观察至 {split['test_target_end']}。边界另剔除 {split['purged_per_index']} 日。",
        "", "## 总成绩", "",
        "Brier越低越好；AUC衡量排序区分能力，0.5为随机区分；准确率使用统一0.5阈值。",
        "",
        "| 指数 | 版本 | Brier | 方向准确率 | AUC | 平均上涨概率 | 实际上涨率 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for code, name in zip(SPEC.codes, SPEC.names, strict=True):
        item = results["indices"][code]
        for model, metrics in item["metrics"].items():
            rows.append(f"| {name} | {model} | {metrics['brier']:.6f} | {metrics['accuracy']:.2%} | {metrics['auc']:.4f} | {metrics['mean_probability']:.2%} | {metrics['actual_up_rate']:.2%} |")
    rows += ["", "## 预注册的有效性检验", "",
             "改善=Brier对照−Brier候选。区间为6项比较校正后的99.1667%移动块bootstrap区间；包含0则不能排除无增益。", "",
             "| 指数 | 候选对照 | Brier改善 | 校正区间 | 支持增益 |",
             "| --- | --- | ---: | --- | --- |"]
    for code, name in zip(SPEC.codes, SPEC.names, strict=True):
        for comparison, stats in results["indices"][code]["comparisons"].items():
            low, high = stats["family_adjusted_ci"]
            rows.append(f"| {name} | {comparison} | {stats['brier_improvement']:.6f} | [{low:.6f}, {high:.6f}] | {'是' if stats['positive_after_family_correction'] else '未证明'} |")
    rows += ["", "## 分指数判断", ""]
    for code, name in zip(SPEC.codes, SPEC.names, strict=True):
        rows.append(f"- {name}：{results['indices'][code]['verdict']}。")
    rows += ["", "## 数据与复核", "",
             f"- 只读 {results['data']['file_count']} 个Parquet文件，物理体积 {results['data']['total_bytes']/1024**2:.2f} MiB；选中 {results['data']['source_rows']} 行，SSE开市日 {results['data']['sse_open_days']} 个。",
             "- 三指数分别通过重复、空值/非正值、日历覆盖、OHLC、涨跌幅单位和文件分区日期核验。前收盘连续性有3条已批准警告，保留且未修复；见results.json中的逐条记录。未运行DG正式checks，不代表源端独立对账。",
             f"- 读取及质量核验 {results['data']['read_quality_seconds']:.3f} 秒；完整研究计算 {results['compute_seconds']:.3f} 秒。",
             "- 模型参数、特征标准化、方案/代码哈希保存在 results.json；源文件清单在 source_manifest.json；预测明细在 predictions.csv；按年成绩在 yearly_metrics.csv；校准表在 calibration.csv。",
             "- bootstrap区间不包括重新训练带来的全部不确定性；单一时间切分不能证明未来持续有效。当前历史数据可能经过后期修订。",
             "- 所有模型和特征均为首轮固定方法，没有在看测试成绩后挑参数。未证明这一方法有效，不等于证明所有量价方法均无效。",
             "- 无正式Lake/数据库/DG事件写入，无依赖安装，无产品运行时变更。",
             "", "## 复现", "", "```bash",
             ".venv/bin/python -B -m scripts.research.index_market.statistics.index_probability_backtest --output reports/index_probability_backtest_v1_reproduction",
             "```", "", "输出目录必须不存在；新的历史源版本可能使复现结果变化，应核对输入哈希。"]
    (output / "report.md").write_text("\n".join(rows) + "\n")


def run(output: Path) -> dict:
    started = time.monotonic()
    output = safe_output(output)
    output.mkdir(parents=True, exist_ok=False)
    frozen_plan = PLAN.read_bytes()
    metadata = {
        "spec": asdict(SPEC), "model_features": model_features(),
        "plan_sha256_before_run": hashlib.sha256(frozen_plan).hexdigest(),
        "frozen_method_sha256": hashlib.sha256(frozen_plan.split(b"## 7.")[0]).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "versions": {"duckdb": duckdb.__version__, "numpy": np.__version__, "pandas": pd.__version__},
    }
    save_json(output / "run_manifest.json", metadata)
    print("[1/4] Loading bounded Silver index data and checking calendar/quality", flush=True)
    connection, evidence, _ = load_lake()
    try:
        features = connection.execute(feature_sql()).fetchdf()
    finally:
        connection.close()
    train, test, split = split_features(features)
    save_json(output / "source_manifest.json", evidence.pop("files"))
    print(f"[2/4] Split frozen: {json.dumps(split, ensure_ascii=False)}", flush=True)
    results = {**metadata, "data": evidence, "split": split, "indices": {}}
    prediction_parts, yearly_rows, calibration_rows = [], [], []
    for code, name in zip(SPEC.codes, SPEC.names, strict=True):
        train_index = train[train.ts_code == code].sort_values("trade_date")
        test_index = test[test.ts_code == code].sort_values("trade_date")
        y_train = train_index.y.to_numpy(dtype=float)
        y_test = test_index.y.to_numpy(dtype=float)
        probabilities = {"frequency": np.full(len(y_test), y_train.mean())}
        fitted = {}
        for model_name, columns in model_features().items():
            model = fit_logistic(train_index[list(columns)].to_numpy(dtype=float), y_train)
            fitted[model_name] = {"columns": columns, **model}
            probabilities[model_name] = predict_logistic(model, test_index[list(columns)].to_numpy(dtype=float))
        metrics = {key: score(y_test, p) for key, p in probabilities.items()}
        candidate = probabilities["price_amount_volume"]
        comparisons = {
            "full_vs_frequency": bootstrap_comparison(y_test, probabilities["frequency"], candidate),
            "full_vs_price": bootstrap_comparison(y_test, probabilities["price"], candidate),
        }
        supported = all(item["positive_after_family_correction"] for item in comparisons.values())
        result = {
            "name": name, "training_up_rate": float(y_train.mean()),
            "models": fitted, "metrics": metrics, "comparisons": comparisons,
            "verdict": "本次留出期支持存在预测增益，仍需检查校准与年度稳定性" if supported else "未通过预注册增益门槛，尚未证明该方法有效",
        }
        results["indices"][code] = result
        part = test_index[["ts_code", "trade_date", "target_date", "next_return", "y"]].copy()
        for model_name, p in probabilities.items():
            part[f"p_{model_name}"] = p
            for year in sorted(part.trade_date.dt.year.unique()):
                mask = part.trade_date.dt.year == year
                yearly_rows.append({"ts_code": code, "year": int(year), "model": model_name, **score(y_test[mask], p[mask])})
            bins = np.minimum((p*10).astype(int), 9)
            for bin_id in range(10):
                selected = bins == bin_id
                calibration_rows.append({
                    "ts_code": code, "model": model_name, "bin_left": bin_id/10,
                    "bin_right": (bin_id+1)/10, "n": int(selected.sum()),
                    "mean_probability": float(p[selected].mean()) if selected.any() else None,
                    "actual_up_rate": float(y_test[selected].mean()) if selected.any() else None,
                })
        prediction_parts.append(part)
        print(f"[3/4] {name}: {json.dumps(metrics, ensure_ascii=False)}", flush=True)
        if time.monotonic()-started > SPEC.max_seconds:
            raise RuntimeError("experiment exceeded 120-second computation budget")
    predictions = pd.concat(prediction_parts, ignore_index=True)
    predictions.to_csv(output / "predictions.csv", index=False, float_format="%.17g")
    pd.DataFrame(yearly_rows).to_csv(output / "yearly_metrics.csv", index=False)
    pd.DataFrame(calibration_rows).to_csv(output / "calibration.csv", index=False)
    # Re-read persisted probabilities and verify headline metrics independently with SQL.
    with duckdb.connect(":memory:") as verification:
        readback = {}
        for model_name in ("frequency", *model_features()):
            values = verification.execute(f"""
              SELECT ts_code, count(*) AS n, avg(pow(p_{model_name}-y,2)) AS brier,
                avg(CAST((p_{model_name}>=0.5)=(y=1) AS DOUBLE)) AS accuracy
              FROM read_csv_auto(?) GROUP BY ts_code ORDER BY ts_code
            """, [str(output / "predictions.csv")]).fetchall()
            for code, n, brier, accuracy in values:
                expected = results["indices"][code]["metrics"][model_name]
                if n != expected["n"] or abs(brier-expected["brier"]) > 1e-12 or abs(accuracy-expected["accuracy"]) > 1e-12:
                    raise RuntimeError("persisted predictions failed independent DuckDB score readback")
                readback[f"{code}/{model_name}"] = {"n": n, "brier": brier, "accuracy": accuracy}
    source_manifest = json.loads((output / "source_manifest.json").read_text())
    for item in source_manifest:
        stat = Path(item["path"]).stat()
        if stat.st_size != item["size"] or stat.st_mtime_ns != item["mtime_ns"]:
            raise RuntimeError("source changed during experiment; do not publish this run")
    results["readback_validation"] = readback
    results["source_stat_unchanged"] = True
    results["compute_seconds"] = time.monotonic()-started
    save_json(output / "results.json", results)
    write_report(output, results)
    print(f"[4/4] Verified persisted scores and unchanged source files: {output / 'report.md'}", flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New result directory under repository reports")
    args = parser.parse_args()
    run(args.output)
