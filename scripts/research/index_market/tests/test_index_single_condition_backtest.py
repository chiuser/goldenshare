from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from scripts.research.index_market.statistics import index_single_condition_backtest as study


def sample():
    dates = pd.bdate_range("2010-02-01", periods=5)
    return pd.concat([pd.DataFrame({"ts_code": code, "phase": "D", "trade_date": dates[:4],
                                   "target_date": dates[1:], "r5": [-.1, -.1, .1, .1],
                                   "sigma20": [1., 2., 3., 4.], "next_return": [-.01, .01, .02, .04]})
                      for code in study.first.SPEC.codes], ignore_index=True)


def test_fit_hand_calculated():
    models = study.fit_models(sample())
    for m in models.values():
        assert m["threshold"] == 2.5
        assert m["p_down"] == .5 and m["p_up"] == 1 and m["p_base"] == .75
        assert m["abs_low"] == .01 and m["abs_high"] == .03 and m["abs_base"] == .02


def test_fit_rejects_validation_and_empty_groups():
    frame = sample()
    frame.loc[0, "phase"] = "V1"
    with pytest.raises(ValueError, match="only D"):
        study.fit_models(frame)
    frame.phase = "D"
    frame.r5 = 1.
    with pytest.raises(ValueError, match="empty discovery"):
        study.fit_models(frame)


def test_predictions_ignore_future_labels_and_use_fixed_threshold():
    frame = sample()
    models = study.fit_models(frame)
    frame.phase = "V1"
    frame.loc[0, "r5"] = 0
    frame.loc[0, "sigma20"] = 2.5
    before = study.predict(frame, models)
    frame.next_return = -999
    after = study.predict(frame, models)
    pd.testing.assert_frame_equal(before[["p", "abs_pred"]], after[["p", "abs_pred"]])
    row = before.iloc[0]
    assert row.direction_group == -1 and row.p == .75 and row.risk_group == 0 and row.abs_pred == .01
    counts = study.coverage(before)
    assert all(r["n0"]+r["n1"]+r["flat"] == r["total"] for r in counts)
    assert len(before) == len(frame)


def test_unknown_index_and_invalid_predictors_fail():
    frame = sample()
    models = study.fit_models(frame)
    frame.loc[0, "ts_code"] = "unknown"
    with pytest.raises(ValueError, match="unknown"):
        study.predict(frame, models)
    frame = sample()
    frame.loc[0, "r5"] = np.nan
    with pytest.raises(ValueError, match="nonfinite"):
        study.predict(frame, models)


def test_statistic_vector_hand_calculated_and_paired():
    p = study.predict(sample(), study.fit_models(sample())).iloc[:4]
    stat = study.statistics_at(p, np.arange(4)[None, :])[0]
    np.testing.assert_allclose(stat, [.5, .02, .0625, .0001], atol=1e-15)
    repeated = study.statistics_at(p, np.array([[0, 1, 2, 3], [3, 2, 1, 0]]))
    np.testing.assert_allclose(repeated[0], repeated[1])


def test_bootstrap_reproducible_and_sql_roundtrip(tmp_path):
    frame = sample()
    # Isolated synthetic timeline long enough for bounded resampling.
    p = study.predict(frame, study.fit_models(frame))
    p = pd.concat([p[p.ts_code == study.first.SPEC.codes[0]]]*8, ignore_index=True)
    spec = replace(study.SPEC, block_days=4, bootstrap_samples=31, bootstrap_batch=7)
    tests, groups, scores = study.evaluate_phase(p, 42, spec)
    assert tests == study.evaluate_phase(p, 42, spec)[0]
    p.to_csv(tmp_path / "predictions.csv", index=False)
    assert study.verify_saved(tmp_path, groups, [scores]) == {"groups": 4, "scores": 1}
    scores["mse_model"] += 1
    with pytest.raises(AssertionError):
        study.verify_saved(tmp_path, groups, [scores])


def all_tests():
    return [{"ts_code": code, "phase": phase, "kind": kind, "effect": .1, "min_group": 60,
             "valid_fraction": 1., "p_approximate": .0001, "holm_p": None}
            for code in study.first.SPEC.codes for phase in study.second.SPEC.phases for kind in study.KINDS]


def test_association_and_forecast_separate_and_fixed_family():
    tests = all_tests()
    assert all(r["forecast_candidate"] for r in study.screen(tests))
    tests[6]["effect"] = -.1  # first index V1 Brier gain
    decisions = study.screen(tests)
    assert decisions[0]["association_candidate"] and not decisions[0]["forecast_candidate"]
    with pytest.raises(ValueError, match="24 unique"):
        study.screen(tests[5:])


@pytest.mark.parametrize("field,value", [("min_group", 49), ("valid_fraction", .98), ("effect", -.1), ("p_approximate", .5)])
def test_association_gates(field, value):
    tests = all_tests()
    tests[4][field] = value
    assert not study.screen(tests)[0]["association_candidate"]


def test_negative_stable_direction_allowed_but_negative_risk_not():
    tests = all_tests()
    for t in tests:
        if t["kind"] in ("direction_gap", "risk_gap"):
            t["effect"] = -.1
    decisions = study.screen(tests)
    assert decisions[0]["association_candidate"]
    assert not decisions[1]["association_candidate"]
