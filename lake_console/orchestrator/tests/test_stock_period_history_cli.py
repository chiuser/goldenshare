import json

import pytest

from orchestrator.defs.bootstrap.stock_period_history_cli import main


def test_prepare_is_readonly_and_apply_requires_explicit_delete(tmp_path, capsys):
    argv = [
        "--lake-root",
        str(tmp_path / "lake"),
        "--staging-root",
        str(tmp_path / "staging"),
        "--request-id",
        "sample",
    ]
    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert not (tmp_path / "lake").exists() and not (tmp_path / "staging").exists()
    with pytest.raises(SystemExit):
        main(["apply", *argv])
    assert not (tmp_path / "lake").exists()


def test_old_plans_and_old_prod_config_rejected():
    from orchestrator.defs.bootstrap.stock_monthly_history_cli import main as oldmonth
    from orchestrator.defs.bootstrap.stock_weekly_history_cli import main as oldweek
    from orchestrator.defs.run_contracts.configs import StockPeriodRawConfig

    for entry in [oldmonth, oldweek]:
        with pytest.raises(ValueError, match="retired"):
            entry(["apply", "--plan", "old.json"])
    for config in [
        {"delivery_batch_id": "old", "closure_revision": 1},
        {"write_mode": "create_or_identical"},
        {"source": "weekly"},
    ]:
        with pytest.raises(ValueError):
            StockPeriodRawConfig(**config)


def test_events_uses_one_real_run_and_does_no_source_or_copy(tmp_path, monkeypatch):
    from pathlib import Path

    import dagster as dg

    import orchestrator.defs.stock_period_update as update
    from orchestrator.defs.bootstrap import stock_period_history as history
    from orchestrator.defs.io import stock_period_raw as raw
    from tests.test_stock_period_history import args

    kw = args(tmp_path)
    result = history.run_period(**kw)
    versions = {i["target"]: raw.file_version(i["target"]) for i in result["files"]}
    monkeypatch.setattr(
        history, "run_period", lambda **kw: pytest.fail("events downloaded")
    )
    monkeypatch.setattr(
        raw, "execute", lambda *a, **k: pytest.fail("events calculated")
    )
    (tmp_path / "instance").mkdir()
    (tmp_path / "instance/dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    instance = dg.DagsterInstance.local_temp(str(tmp_path / "instance"))
    dispose = instance.dispose
    disposed = []
    monkeypatch.setattr(instance, "dispose", lambda: disposed.append(True))
    monkeypatch.setattr(dg.DagsterInstance, "get", lambda: instance)
    argv = [
        "events",
        "--lake-root",
        str(kw["root"]),
        "--staging-root",
        str(kw["staging"]),
        "--run-id",
        result["run_id"],
    ]
    try:
        original = update.report_file_events

        def fail_month(instance, item, **kwargs):
            if item["freq"] == "month":
                raise OSError("event_down")
            return original(instance, item, **kwargs)

        monkeypatch.setattr(update, "report_file_events", fail_month)
        with pytest.raises(OSError, match="event_down"):
            main(argv)
        assert len(disposed) == 1 and instance.get_runs()[0].is_failure
        assert versions == {p: raw.file_version(p) for p in versions}
        monkeypatch.setattr(update, "report_file_events", original)
        assert main(argv) == 0
        assert len(instance.get_runs()) == 2 and instance.get_runs()[0].is_success
        assert (
            raw.read_json(Path(result["path"]) / "manifest.json")["phase"]
            == "events_complete"
        )
        assert main(argv) == 0
        assert len(instance.get_runs()) == 2 and len(disposed) == 3
        assert versions == {p: raw.file_version(p) for p in versions}
        assert (
            raw.read_json(kw["staging"] / "stock_period/baseline.json")["status"]
            == "files_ready"
        )
    finally:
        dispose()


def test_cli_handoff_is_separate_and_keeps_completed_watermarks(tmp_path, monkeypatch):
    import dagster as dg

    import orchestrator.defs.stock_period_update as update
    from orchestrator.defs.io import stock_period_raw as raw
    from tests.test_stock_period_combined import A, B, row, wire
    from tests.test_stock_period_handoff import captured, options
    from tests.test_stock_period_recovery import daily_source

    kw, run, _ = captured(tmp_path, monkeypatch)
    original = update.handoff_bootstrap
    calls = []

    def source(params):
        calls.append(params)
        if params["freq"] == "month":
            values = [row(A, "20261031", "month", "3")]
            if "ts_code" not in params:
                values.append(row(B, "20261031", "month", "9"))
            return wire(values)
        return daily_source(params)

    def handoff(**kwargs):
        selected = options(kw, run)
        selected.update(kwargs, transport=source)
        return original(**selected)

    monkeypatch.setattr(update, "handoff_bootstrap", handoff)
    (tmp_path / "instance").mkdir()
    (tmp_path / "instance/dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    instance = dg.DagsterInstance.local_temp(str(tmp_path / "instance"))
    dispose = instance.dispose
    disposed = []
    monkeypatch.setattr(instance, "dispose", lambda: disposed.append(True))
    monkeypatch.setattr(dg.DagsterInstance, "get", lambda: instance)
    argv = [
        "handoff",
        "--lake-root",
        str(kw["root"]),
        "--staging-root",
        str(kw["staging"]),
        "--run-id",
        run.name,
    ]
    try:
        assert main(argv) == 0
        assert len(calls) == 4
        assert len(instance.get_runs()) == 1 and instance.get_runs()[0].is_success
        statepath = kw["staging"] / "stock_period/daily.json"
        state = raw.read_json(statepath)
        state["last_refresh"]["week"] = "2026-10-19"
        raw.atomic_json(statepath, state)
        assert main(argv) == 0
        assert len(calls) == 4 and len(instance.get_runs()) == 1
        assert raw.read_json(statepath)["last_refresh"]["week"] == "2026-10-19"
        assert len(disposed) == 2
    finally:
        dispose()
