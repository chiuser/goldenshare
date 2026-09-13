import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from zipfile import ZipFile

import pytest

from scripts.research.index_market.chan import build_cases
from scripts.research.index_market.statistics import index_probability_backtest as first
from scripts.research.index_market.statistics import provenance

ROOT = Path(__file__).resolve().parents[4]
TOPIC = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "reports/index_market_history_20260913"


def test_single_location_roots_and_pytest_discovery():
    assert first.REPO == ROOT == build_cases.REPO == provenance.REPO
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "scripts/research/index_market/tests" in config["tool"]["pytest"]["ini_options"]["testpaths"]
    manifest = json.loads((TOPIC / "migration_20260909.json").read_text())
    for item in manifest["files"]:
        assert not (ROOT / item["old_path"]).exists()
        assert (ROOT / item["new_path"]).is_file()


@pytest.mark.parametrize("name", ["index_probability_backtest", "index_condition_statistics",
                                 "index_single_condition_backtest", "index_risk_baseline_backtest"])
def test_statistics_help_without_running_research(name):
    command = [sys.executable, "-B", "-m", f"scripts.research.index_market.statistics.{name}", "--help"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "--output" in result.stdout


def test_chan_help_without_third_party_or_lake():
    result = subprocess.run([sys.executable, "-B", "-m", "scripts.research.index_market.chan.build_cases", "--help"],
                            cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "--output" in result.stdout and "--chan-source" in result.stdout


@pytest.mark.parametrize("target", ["reports", "reports/stock_chan_research_20260912", "src", "/Volumes/datasource/data_lake"])
def test_chan_rejects_existing_or_unsafe_output_before_source_access(target, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(sys, "argv", ["build_cases", "--chan-source", "/nonexistent/chan", "--output", target])
    with pytest.raises(ValueError, match="output|overwrite"):
        build_cases.main()


def test_prior_source_exact_and_registered_pair_only(tmp_path, monkeypatch):
    source = tmp_path / "script.py"
    source.write_text("current")
    current = hashlib.sha256(source.read_bytes()).hexdigest()
    old = hashlib.sha256(b"old").hexdigest()
    catalog = tmp_path / "migration.json"
    record = {"role": "statistics", "new_path": "script.py", "old_sha256": old, "new_sha256": current}
    catalog.write_text(json.dumps({"files": [record]}))
    monkeypatch.setattr(provenance, "REPO", tmp_path)
    monkeypatch.setattr(provenance, "MIGRATION_MANIFEST", catalog)
    assert provenance.verify_prior_source(source, current)["mode"] == "exact"
    assert provenance.verify_prior_source(source, old)["mode"] == "directory_migration_20260909"
    with pytest.raises(ValueError, match="outside audited"):
        provenance.verify_prior_source(source, "f" * 64)
    source.write_text("unreviewed modification")
    with pytest.raises(ValueError, match="outside audited"):
        provenance.verify_prior_source(source, old)


def test_actual_historical_sources_still_verify():
    pairs = [("index_probability_backtest", "index_probability_backtest_v1_20260908_approved"),
             ("index_condition_statistics", "index_condition_statistics_v1_20260908"),
             ("index_single_condition_backtest", "index_single_condition_v1_20260908"),
             ("index_risk_baseline_backtest", "index_risk_baseline_v1_20260908")]
    for name, directory in pairs:
        module = importlib.import_module(f"scripts.research.index_market.statistics.{name}")
        with ZipFile(ARCHIVE / "statistics.zip") as archive:
            recorded = json.loads(archive.read(f"reports/{directory}/run_manifest.json"))
        check = provenance.verify_prior_source(Path(module.__file__), recorded["script_sha256"])
        assert check["mode"] == "directory_migration_20260909"


def test_all_archived_evidence_matches_original_inventory():
    inventory = json.loads((ARCHIVE / "inventory.json").read_text())
    assert len(inventory["records"]) == inventory["original_files"] == 668
    actual = set()
    for name, info in inventory["archives"].items():
        raw = (ARCHIVE / name).read_bytes()
        assert len(raw) == info["bytes"]
        assert hashlib.sha256(raw).hexdigest() == info["sha256"]
        with ZipFile(ARCHIVE / name) as archive:
            names = archive.namelist()
            assert len(names) == len(set(names))
            for key in names:
                assert key.startswith("reports/") and ".." not in Path(key).parts
                assert key not in actual
                expected = inventory["records"][key]
                assert expected["archive"] == name
                data = archive.read(key)
                assert len(data) == expected["bytes"]
                assert hashlib.sha256(data).hexdigest() == expected["sha256"]
                actual.add(key)
    assert actual == set(inventory["records"])


def test_live_source_gate_keeps_exact_archived_manifest(monkeypatch):
    from scripts.research.index_market.chan import stock_qfq_run
    key = "reports/chan_minute_variant_a_20260909/manifest.json"
    with ZipFile(ARCHIVE / "index_chan.zip") as archive:
        data = archive.read(key)
    assert (ROOT / key).read_bytes() == data
    source = json.loads(data)["source"]
    # No third-party loading or Lake access in the default tests.
    monkeypatch.setattr(stock_qfq_run, "verify_variant_source", lambda path: source)
    assert stock_qfq_run.source_gate() == source
