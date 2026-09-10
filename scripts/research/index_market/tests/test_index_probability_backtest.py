from dataclasses import replace
from pathlib import Path
from statistics import stdev

import duckdb
import numpy as np
import pandas as pd
import pytest

from scripts.research.index_market.statistics.index_probability_backtest import (
    SPEC,
    bootstrap_comparison,
    feature_sql,
    fit_logistic,
    model_features,
    objective_gradient_hessian,
    predict_logistic,
    safe_output,
    score,
    split_features,
    validate_observations,
)


def observations(n=30):
    dates = pd.bdate_range("2010-01-04", periods=n)
    parts = []
    for code in SPEC.codes:
        close = np.arange(n, dtype=float) + 100.0
        previous = close - 1.0
        amount = np.arange(1, n+1, dtype=float)
        parts.append(pd.DataFrame({
            "ts_code": code, "trade_date": dates, "partition_date": dates,
            "open": close, "high": close+1, "low": close-1,
            "close": close, "pre_close": previous,
            "pct_chg": 100.0*(close/previous-1), "amount": amount, "vol": amount*2,
        }))
    return pd.concat(parts, ignore_index=True), pd.DataFrame({"trade_date": dates})


def compute_features(frame):
    with duckdb.connect(":memory:") as connection:
        connection.register("observations", frame)
        return connection.execute(feature_sql()).fetchdf()


def test_window_gold_values_and_prior_median_excludes_today():
    frame, _ = observations()
    target = frame.groupby("ts_code").cumcount() == 20
    frame.loc[target, "amount"] = 210.0
    frame.loc[target, "vol"] = 420.0
    features = compute_features(frame)
    row = features[features.ts_code == SPEC.codes[0]].iloc[20]
    assert row.r1 == pytest.approx(1/119)
    assert row.r5 == pytest.approx(1/23)
    assert row.r20 == pytest.approx(0.2)
    assert row.a20 == pytest.approx(np.log(20))  # 210 / median(1..20) = 20.
    assert row.v20 == pytest.approx(np.log(20))
    assert row.sigma20 == pytest.approx(stdev([1/k for k in range(100, 120)]))
    assert row.next_return == pytest.approx(1/120)
    assert row.y == 1
    assert pd.isna(features[features.ts_code == SPEC.codes[0]].iloc[-1].y)


def test_future_changes_cannot_change_past_features():
    frame, _ = observations(60)
    before = compute_features(frame)
    cutoff = frame.trade_date.sort_values().unique()[35]
    altered = frame.copy()
    future = altered.trade_date > cutoff
    altered.loc[future, ["close", "amount", "vol"]] *= 100
    after = compute_features(altered)
    columns = ["ts_code", "trade_date", *model_features()["price_amount_volume"]]
    pd.testing.assert_frame_equal(
        before.loc[before.trade_date <= cutoff, columns].reset_index(drop=True),
        after.loc[after.trade_date <= cutoff, columns].reset_index(drop=True),
    )


def test_split_purges_boundary_label_and_has_no_overlapping_dates():
    frame, _ = observations(1200)
    features = compute_features(frame)
    train, test, audit = split_features(features)
    assert audit["eligible_per_index"] == 1179
    assert audit["nominal_train_per_index"] == 825
    assert audit["train_per_index"] == 824
    assert audit["test_per_index"] == 354
    assert audit["purged_per_index"] == 1
    assert audit["warmup_excluded_per_index"] == 20
    assert audit["last_unlabelled_per_index"] == 1
    assert train.target_date.max() < test.trade_date.min()
    assert set(train.trade_date).isdisjoint(test.trade_date)


def test_logistic_constant_features_equal_frequency_without_test_scaling():
    x = np.full((100, 2), 3.0)
    y = np.array([1.0]*60 + [0.0]*40)
    fitted = fit_logistic(x, y)
    assert fitted["mean"] == [3.0, 3.0]
    assert fitted["scale"] == [1.0, 1.0]
    assert fitted["beta"][0] == pytest.approx(np.log(1.5))
    assert np.allclose(predict_logistic(fitted, np.array([[300., -200.]])), 0.6)
    assert fitted["mean"] == [3.0, 3.0]


def test_logistic_gradient_and_hessian_against_finite_differences():
    design = np.array([[1., -2., .1], [1., 0., 2.], [1., .5, -.3], [1., 2., 1.]])
    y = np.array([0., 1., 0., 1.])
    beta = np.array([.1, -.2, .3])
    _, gradient, hessian = objective_gradient_hessian(design, y, beta, .01)
    eps = 1e-5
    for j in range(3):
        plus, minus = beta.copy(), beta.copy()
        plus[j] += eps
        minus[j] -= eps
        fp, gp, _ = objective_gradient_hessian(design, y, plus, .01)
        fm, gm, _ = objective_gradient_hessian(design, y, minus, .01)
        assert gradient[j] == pytest.approx((fp-fm)/(2*eps), abs=1e-8)
        assert np.allclose(hessian[:, j], (gp-gm)/(2*eps), atol=1e-8)


def test_logistic_learns_direction_and_fails_closed_on_nonconvergence():
    x = np.arange(-50, 50, dtype=float).reshape(-1, 1)
    y = (x[:, 0] > 0).astype(float)
    fitted = fit_logistic(x, y)
    probabilities = predict_logistic(fitted, x)
    assert probabilities[0] < .1
    assert probabilities[-1] > .9
    assert fitted["gradient_inf_norm"] <= SPEC.gradient_tolerance
    with pytest.raises(RuntimeError, match="did not converge"):
        fit_logistic(x, y, replace(SPEC, max_iterations=1))
    with pytest.raises(ValueError, match="both outcome"):
        fit_logistic(x, np.ones(100))


def test_probability_score_gold_values_and_auc_ties():
    metrics = score(np.array([1., 0.]), np.array([.8, .8]))
    assert metrics["brier"] == pytest.approx(.34)
    assert metrics["auc"] == .5
    assert metrics["accuracy"] == .5
    assert score(np.array([0., 1.]), np.array([.2, .8]))["auc"] == 1.0
    with pytest.raises(ValueError):
        score(np.array([1.]), np.array([1.1]))


def test_bootstrap_identical_models_have_zero_interval_and_is_deterministic():
    y = np.tile([0., 1.], 100)
    p = np.full(200, .5)
    small_spec = replace(SPEC, bootstrap_samples=200)
    result = bootstrap_comparison(y, p, p, small_spec)
    assert result["ci95"] == [0., 0.]
    assert result["family_adjusted_ci"] == [0., 0.]
    assert result["positive_after_family_correction"] is False
    assert result == bootstrap_comparison(y, p, p, small_spec)


def test_valid_observations_and_calendar():
    frame, calendar = observations()
    assert validate_observations(frame, calendar)[SPEC.codes[0]]["rows"] == 30


def test_only_exact_approved_discontinuity_is_warning_and_close_features_unchanged():
    frame, calendar = observations()
    code_mask = frame.ts_code == "000300.SH"
    before_day = code_mask & (frame.trade_date == "2010-01-25")
    warning_day = code_mask & (frame.trade_date == "2010-01-26")
    frame.loc[before_day, "close"] = 3328.014
    frame.loc[warning_day, "close"] = 3242.797
    frame["open"] = frame.close
    frame["high"] = frame.close+1
    frame["low"] = frame.close-1
    frame["pre_close"] = frame.groupby("ts_code").close.shift(1).fillna(99)
    frame["pct_chg"] = 100*(frame.close/frame.pre_close-1)
    before = compute_features(frame)
    frame.loc[warning_day, "pre_close"] = 3325.691
    frame["pct_chg"] = 100*(frame.close/frame.pre_close-1)
    profiles = validate_observations(frame, calendar)
    assert len(profiles["000300.SH"]["approved_pre_close_warnings"]) == 1
    assert profiles["000300.SH"]["rows"] == 30
    pd.testing.assert_frame_equal(before, compute_features(frame))
    frame.loc[warning_day, "pre_close"] += .01
    frame["pct_chg"] = 100*(frame.close/frame.pre_close-1)
    with pytest.raises(ValueError, match="unapproved pre_close"):
        validate_observations(frame, calendar)


def test_unknown_pre_close_discontinuity_still_blocks():
    frame, calendar = observations()
    frame.loc[5, "pre_close"] -= 1
    frame["pct_chg"] = 100*(frame.close/frame.pre_close-1)
    with pytest.raises(ValueError, match="unapproved pre_close"):
        validate_observations(frame, calendar)


@pytest.mark.parametrize("corruption", ["duplicate", "missing_day", "null", "zero", "negative", "wrong_pct", "wrong_partition", "wrong_ohlc"])
def test_invalid_observations_fail_closed(corruption):
    frame, calendar = observations()
    if corruption == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    elif corruption == "missing_day":
        frame = frame.drop(index=0)
    elif corruption == "null":
        frame.loc[0, "amount"] = np.nan
    elif corruption == "zero":
        frame.loc[0, "vol"] = 0
    elif corruption == "negative":
        frame.loc[0, "close"] = -1
    elif corruption == "wrong_pct":
        frame.loc[0, "pct_chg"] = 10000
    elif corruption == "wrong_partition":
        frame.loc[0, "partition_date"] += pd.Timedelta(days=1)
    elif corruption == "wrong_ohlc":
        frame.loc[0, "high"] = 1
    with pytest.raises(ValueError):
        validate_observations(frame, calendar)


def test_output_refuses_lake_broad_paths_and_existing_directory(tmp_path, monkeypatch):
    for path in (Path("/Volumes/datasource/data_lake"), Path("reports"), Path("reports/../src")):
        with pytest.raises(ValueError):
            safe_output(path)
    monkeypatch.setattr("scripts.research.index_market.statistics.index_probability_backtest.REPO", tmp_path)
    existing = tmp_path / "reports" / "existing"
    existing.mkdir(parents=True)
    with pytest.raises(ValueError, match="overwrite"):
        safe_output(existing)
    assert safe_output(tmp_path / "reports" / "new") == tmp_path / "reports" / "new"


def test_source_has_no_production_runtime_or_write_lake_dependencies():
    source = (Path(__file__).resolve().parents[1] / "statistics/index_probability_backtest.py").read_text()
    for forbidden in ("import dagster", "import orchestrator", "import src.", "INSTALL ", "os.replace(", "to_parquet("):
        assert forbidden not in source
    assert "enable_external_access = false" in source
    assert "hive_partitioning=false" in source
