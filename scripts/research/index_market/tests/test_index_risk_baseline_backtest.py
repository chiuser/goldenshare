from dataclasses import replace

import duckdb
import numpy as np
import pandas as pd
import pytest

from scripts.research.index_market.statistics import index_risk_baseline_backtest as study


def observations():
    returns = np.full(45, .01)
    returns[0] = 0
    returns[20] = .21
    return pd.DataFrame({"ts_code": "000001.SH", "trade_date": pd.bdate_range("2010-01-04", periods=45),
                         "close": 100*np.cumprod(1+returns), "amount": 100., "vol": 100.})


def features(frame):
    with duckdb.connect(":memory:") as con:
        con.register("observations", frame)
        return con.execute(study.risk_feature_sql()).fetchdf()


def test_twenty_day_golden_window_current_day_and_warmup():
    result = features(observations())
    assert result.abs20.iloc[:20].isna().all()
    assert result.abs20_count.iloc[20] == 20
    np.testing.assert_allclose(result.abs20.iloc[[20, 21, 39, 40]], [.02, .02, .02, .01], atol=1e-12)
    study.verify_rolling(result)
    study.require_complete_windows(result.iloc[20:])
    with pytest.raises(ValueError, match="20 finite"):
        study.require_complete_windows(result.iloc[19:])


def test_future_prices_do_not_change_earlier_rolling_predictions():
    frame = observations()
    old = features(frame)
    frame.loc[25:, "close"] *= 10
    new = features(frame)
    np.testing.assert_allclose(old.abs20.iloc[:25], new.abs20.iloc[:25], equal_nan=True)


def test_window_computed_before_boundary_exclusion():
    full = features(observations())
    retained = full.drop(index=20)
    assert retained.loc[21, "abs20"] == pytest.approx(.02)
    # Recomputing after dropping the boundary would lose its known .21 return.
    incorrect = retained.r1.abs().rolling(20).mean()
    assert incorrect.loc[21] == pytest.approx(.01)


def test_different_window_rejected_and_bad_recompute_detected():
    with pytest.raises(ValueError, match="20-day"):
        study.risk_feature_sql(replace(study.SPEC, window=5))
    frame = features(observations())
    frame.loc[20, "abs20"] += .1
    with pytest.raises(AssertionError):
        study.verify_rolling(frame)


def paired():
    return pd.DataFrame({"ts_code": "000001.SH", "phase": "V1", "next_return": -.02,
                         "abs20": .03, "abs_pred": .02, "abs_base": .04}, index=range(60))


def test_loss_sign_hand_values_reproducible_bootstrap_and_sql(tmp_path):
    part = paired()
    spec = replace(study.SPEC, bootstrap_samples=101, bootstrap_batch=7)
    row = study.compare(part, 42, spec)
    assert row == study.compare(part, 42, spec)
    assert row["effect_rolling_minus_fixed"] == pytest.approx(.0001)
    assert row["fixed_relative_gain"] == pytest.approx(1.)
    assert row["rolling_relative_gain"] is None
    scores = study.score_phase(part)
    np.testing.assert_allclose([s["mse"] for s in scores], [.0004, 0., .0001])
    np.testing.assert_allclose([s["mae"] for s in scores], [.02, 0., .01])
    part.to_csv(tmp_path / "predictions.csv", index=False)
    assert study.verify_saved(tmp_path, scores) == 3
    scores[0]["mse"] = 1.
    with pytest.raises(AssertionError):
        study.verify_saved(tmp_path, scores)


def test_equal_predictions_zero_effect():
    part = paired()
    part.abs20 = part.abs_pred
    result = study.compare(part, 42, replace(study.SPEC, bootstrap_samples=25))
    assert result["effect_rolling_minus_fixed"] == 0
    assert result["p_approximate"] == 1
    assert result["ci95"] == [0., 0.]


def test_insufficient_or_invalid_paired_dates_rejected():
    with pytest.raises(ValueError, match="too few"):
        study.compare(paired().head(49), 42)
    part = paired()
    part.loc[0, "abs20"] = np.nan
    with pytest.raises(ValueError, match="nonfinite"):
        study.compare(part, 42)
    with pytest.raises(ValueError, match="invalid prediction"):
        study.score_phase(part)


def comparisons():
    return [{"ts_code": code, "phase": phase, "n": 100, "effect_rolling_minus_fixed": .1,
             "p_approximate": .0001, "holm_p": None}
            for code in study.first.SPEC.codes for phase in ("V1", "V2")]


def test_fixed_or_rolling_can_win_but_not_mixed_or_missing():
    rows = comparisons()
    assert all(r["verdict"] == "fixed_better" for r in study.classify(rows))
    for row in rows:
        row["effect_rolling_minus_fixed"] = -.1
    assert all(r["verdict"] == "rolling_better" for r in study.classify(rows))
    rows[0]["effect_rolling_minus_fixed"] = .1
    assert study.classify(rows)[0]["verdict"] == "no_cross_phase_evidence"
    with pytest.raises(ValueError, match="six"):
        study.classify(rows[:-1])


@pytest.mark.parametrize("field,value", [("p_approximate", .9), ("n", 49)])
def test_both_phases_must_pass(field, value):
    rows = comparisons()
    rows[0][field] = value
    assert study.classify(rows)[0]["verdict"] == "no_cross_phase_evidence"


def test_prior_prediction_values_and_keys_cannot_change():
    current = paired().assign(trade_date=pd.bdate_range("2010-01-04", periods=60))
    prior = current.copy()
    study.verify_prior_predictions(current, prior)
    prior.loc[0, "abs_pred"] += .1
    with pytest.raises(AssertionError):
        study.verify_prior_predictions(current, prior)
    with pytest.raises(AssertionError):
        study.verify_prior_predictions(current, current.iloc[1:])
