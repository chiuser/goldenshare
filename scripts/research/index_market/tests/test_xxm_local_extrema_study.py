"""New output and source-boundary checks; never touch an existing report."""
import json

import pytest

from scripts.research.index_market.xxm import local_extrema_study as study


def test_existing_output_is_rejected_before_source_access(monkeypatch, tmp_path):
    monkeypatch.setattr(study, "ROOT", tmp_path)
    out = tmp_path / "reports/xxm_local_extrema_trial_existing"
    out.mkdir(parents=True)
    sentinel = out / "old.json"
    sentinel.write_text('{"original":true}')
    monkeypatch.setattr(study, "protected_files", lambda: pytest.fail("Must reject before reading"))
    with pytest.raises(ValueError, match="existing"):
        study.main(["--output", str(out)])
    assert sentinel.read_text() == '{"original":true}'


def test_nonreport_output_is_rejected_without_creating_it(monkeypatch, tmp_path):
    monkeypatch.setattr(study, "ROOT", tmp_path)
    out = tmp_path / "formal_data"
    with pytest.raises(ValueError, match="reports"):
        study.main(["--output", str(out)])
    assert not out.exists()


def test_atomic_report_unit_refuses_overwrite(tmp_path):
    study.save_new(tmp_path, "unit.json", {"literal": 1})
    with pytest.raises(ValueError, match="overwrite"):
        study.save_new(tmp_path, "unit.json", {"literal": 2})
    assert json.loads((tmp_path / "unit.json").read_text()) == {"literal": 1}
    assert not (tmp_path / "unit.json.partial").exists()


def test_changed_frozen_source_is_rejected(monkeypatch, tmp_path):
    case = study.CASES[0]
    path = tmp_path / case.path
    path.parent.mkdir(parents=True)
    path.write_text("[]")
    with pytest.raises(ValueError, match="frozen"):
        study.read_case(case, tmp_path)


def test_generated_performance_input_has_bounded_scanner_state():
    import time

    # Reduced during unit tests; runner separately measures 100,000 points.
    from src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import LocalExtremaScanner
    scanner = LocalExtremaScanner()
    count = 0
    for i in range(10_000):
        count += scanner.step(f"{i:09d}", (0, 1, 2, 1, 0)[i % 5]) is not None
    assert count == 3999 and scanner.count == 10_000
    assert not any(isinstance(value, (list, dict, set)) for value in vars(scanner).values())
