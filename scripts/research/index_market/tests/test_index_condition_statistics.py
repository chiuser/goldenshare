"""Temporal isolation and statistical accounting for the frozen second experiment."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from scripts.research.index_market.statistics import index_condition_statistics as study


def synthetic():
    dates = pd.bdate_range("2010-02-01", periods=91)
    frames = []
    for code in study.first.SPEC.codes:
        frames.append(pd.DataFrame({
            "ts_code": code, "trade_date": dates[:-1], "target_date": dates[1:],
            "r1": .01, "r5": np.where(np.arange(90) % 2, .02, -.02),
            "r20": .03, "sigma20": np.linspace(.005, .03, 90),
            "a20": np.sin(np.arange(90)), "v20": np.cos(np.arange(90)),
            "next_return": np.where(np.arange(90) % 3, .01, -.02),
            "y": (np.arange(90) % 3 != 0).astype(float),
        }))
    spec = replace(study.SPEC, expected_training_days=90,
                   signal_end=str(dates[-2].date()), source_end=str(dates[-1].date()))
    return pd.concat(frames, ignore_index=True), spec


def test_split_purges_cross_phase_labels():
    frame, spec = synthetic()
    retained, excluded, phases = study.split_training(frame, spec)
    assert [r["actual_per_index"] for r in phases] == [29, 29, 30]
    assert len(excluded) == 6
    assert len(retained) == 264
    for earlier, later in [("D", "V1"), ("V1", "V2")]:
        assert retained.loc[retained.phase == earlier, "target_date"].max() < retained.loc[retained.phase == later, "trade_date"].min()


def test_split_rejects_former_test_labels():
    frame, spec = synthetic()
    frame.loc[0, "target_date"] = pd.Timestamp(spec.source_end) + pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="original test"):
        study.split_training(frame, spec)


def test_split_rejects_missing_index_day():
    frame, spec = synthetic()
    with pytest.raises(ValueError, match="date set"):
        study.split_training(frame.drop(index=0), spec)


def test_validation_values_cannot_change_discovery_thresholds():
    frame, spec = synthetic()
    phased, _, _ = study.split_training(frame, spec)
    before = study.fit_thresholds(phased[phased.phase == "D"], spec)
    phased.loc[phased.phase != "D", ["a20", "v20", "sigma20", "next_return"]] = 100
    assert study.fit_thresholds(phased[phased.phase == "D"], spec) == before
    with pytest.raises(ValueError, match="only be fitted"):
        study.fit_thresholds(phased, spec)


def test_group_boundaries_middle_flat_and_future_outcome_independence():
    frame, spec = synthetic()
    phased, _, _ = study.split_training(frame, spec)
    thresholds = study.fit_thresholds(phased[phased.phase == "D"], spec)
    for code in study.first.SPEC.codes:
        idx = phased.index[phased.ts_code == code][:4]
        t = thresholds[code]
        phased.loc[idx, "r5"] = [.01, -.01, .01, 0]
        phased.loc[idx, "sigma20"] = t["sigma20_median"]
        phased.loc[idx, "a20"] = [t["amount"]["low"], t["amount"]["high"],
                                    (t["amount"]["low"] + t["amount"]["high"])/2, t["amount"]["low"]]
    assigned = study.assign_groups(phased, thresholds)
    for code in study.first.SPEC.codes:
        part = assigned[assigned.ts_code == code].head(4)
        assert part.amount_group.tolist() == [4, 1, -1, -1]
        assert part.amount_exclusion.tolist() == ["included", "included", "middle_activity", "flat_r5"]
    phased.next_return = 999
    changed = study.assign_groups(phased, thresholds)
    pd.testing.assert_series_equal(assigned.amount_group, changed.amount_group)
    pd.testing.assert_series_equal(assigned.volume_group, changed.volume_group)


def test_empty_discovery_and_collapsed_thresholds_fail():
    frame, spec = synthetic()
    phased, _, _ = study.split_training(frame, spec)
    with pytest.raises(ValueError):
        study.fit_thresholds(phased.iloc[:0], spec)
    phased.a20 = 0
    with pytest.raises(ValueError, match="collapse"):
        study.fit_thresholds(phased[phased.phase == "D"], spec)


def test_group_moments_loss_denominator_and_excluded_dates():
    frame = pd.DataFrame({"next_return": [.1, -.2, 0, .9]})
    counts, means, losses, conditional = study.group_moments(np.array([0, 0, 0, -1]), study.outcomes(frame))
    assert counts.tolist() == [3, 0, 0, 0, 0, 0, 0, 0]
    np.testing.assert_allclose(means[0], [1/3, -.1/3, .3/3, .2/3])
    assert losses[0] == 1 and conditional[0] == .2
    assert np.isnan(means[1:]).all()


def test_blocks_are_contiguous_bounded_and_reproducible():
    spec = replace(study.SPEC, block_days=4)
    a = study.block_draws(11, 5, np.random.default_rng(42), spec)
    b = study.block_draws(11, 5, np.random.default_rng(42), spec)
    np.testing.assert_array_equal(a, b)
    assert a.min() >= 0 and a.max() < 11 and a.shape == (5, 11)
    np.testing.assert_array_equal(np.diff(a[:, :4]), np.ones((5, 3)))
    with pytest.raises(ValueError, match="shorter"):
        study.block_draws(3, 1, np.random.default_rng(42), spec)


def test_bootstrap_keeps_groups_paired_with_outcomes_and_missing_groups():
    groups = np.tile([0, 1, -1], 20)
    values = np.repeat(groups[:, None], 4, axis=1).astype(float)
    spec = replace(study.SPEC, bootstrap_samples=31, bootstrap_batch=7, block_days=4)
    a = study.bootstrap_groups(groups, values, 42, spec)
    b = study.bootstrap_groups(groups, values, 42, spec)
    np.testing.assert_array_equal(a, b)
    np.testing.assert_allclose(a[:, 0], 0)
    np.testing.assert_allclose(a[:, 1], 1)
    assert np.isnan(a[:, 2:]).all()
    assert study.finite_interval(a[:, 2, 0]) == (None, 0)


def test_holm_known_values_and_invalid_inputs():
    np.testing.assert_allclose(study.holm_adjust(np.array([.01, .04, .03])), [.03, .06, .06])
    with pytest.raises(ValueError):
        study.holm_adjust(np.array([np.nan]))


def test_centered_bootstrap_p_exact_small_example():
    assert study.centered_bootstrap_p(.1, np.array([.1, .1, .3])) == .5
    assert study.centered_bootstrap_p(0, np.array([0., .1])) == 1
    assert study.centered_bootstrap_p(np.nan, np.array([np.nan])) == 1


def candidate_rows():
    return [{"phase": p, "n_low": 60, "n_high": 60, "bootstrap_valid_fraction": 1.,
             "effect_high_minus_low": .1, "holm_p": None if p == "D" else .01}
            for p in study.SPEC.phases]


@pytest.mark.parametrize("field,value", [("n_low", 49), ("bootstrap_valid_fraction", .98),
                                         ("effect_high_minus_low", -.1), ("holm_p", .06)])
def test_each_candidate_gate_is_required(field, value):
    rows = candidate_rows()
    assert study.candidate_decision(rows)["candidate"]
    rows[1][field] = value
    assert not study.candidate_decision(rows)["candidate"]


def test_full_holm_family_keeps_small_groups_and_excludes_volume():
    comparisons = []
    for code in study.first.SPEC.codes:
        for trend in ("down", "up"):
            for volatility in ("low", "high"):
                for metric in study.SPEC.tested_metrics:
                    for row in candidate_rows():
                        comparisons.append({**row, "ts_code": code, "trend": trend,
                                            "volatility": volatility, "metric": metric,
                                            "view": "amount", "p_approximate": .0001})
    comparisons[1]["n_low"] = 49
    volume = {**comparisons[1], "view": "volume", "holm_p": None}
    comparisons.append(volume)
    decisions = study.adjust_and_screen(comparisons)
    assert comparisons[1]["holm_p"] == 1
    assert volume["holm_p"] is None
    assert len(decisions) == 24
    assert sum(r["candidate"] for r in decisions) == 23
    with pytest.raises(ValueError, match="48"):
        study.adjust_and_screen(comparisons[2:])


def test_source_version_mismatch_is_rejected(tmp_path):
    path = tmp_path / "source"
    path.write_bytes(b"data")
    stat = path.stat()
    row = {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    study.source_versions_unchanged([row], [dict(row)])
    with pytest.raises(ValueError, match="first run"):
        study.source_versions_unchanged([row], [{**row, "size": 99}])
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="during"):
        study.source_versions_unchanged([row], [dict(row)])


def test_independent_sql_verifies_exported_statistics(tmp_path):
    frame = pd.DataFrame({"ts_code": "000001.SH", "phase": "D", "amount_group": [0, 0, -1],
                          "volume_group": [0, 0, -1], "next_return": [.1, -.2, .9]})
    frame.to_csv(tmp_path / "conditional_observations.csv", index=False)
    rows = [{"ts_code": "000001.SH", "phase": "D", "view": view, "group": 0,
             "n": 2, "negative_days": 1, "up_rate": .5, "mean_return": -.05,
             "mean_abs_return": .15, "mean_downside": .1, "mean_loss_on_negative_days": .2}
            for view in study.VIEWS]
    assert study.verify_saved_groups(tmp_path, rows) == 2
    rows[0]["n"] = 3
    with pytest.raises(RuntimeError, match="count mismatch"):
        study.verify_saved_groups(tmp_path, rows)
