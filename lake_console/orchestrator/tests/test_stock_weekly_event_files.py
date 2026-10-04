"""Real temporary Parquet and sealed proof; no formal resources or source calls."""

import json
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap import stock_weekly_event_instance as adapter
from orchestrator.defs.bootstrap.stock_weekly_candidates import fingerprint
from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.bootstrap.stock_weekly_event_files import (
    audit_weekly_event_files,
)
from orchestrator.defs.run_contracts.stock_weekly import StockWeeklySource
from orchestrator.defs.stock_weekly_point import deliver_stock_weekly_point

from .test_stock_weekly_definitions import frame_for


@pytest.mark.parametrize("source", tuple(StockWeeklySource))
def test_annual_proof_matches_real_file_and_rejects_changes(tmp_path, source):
    codes = tmp_path / "codes.csv"
    codes.write_text("ts_code\n000005.SZ\n")
    result = deliver_stock_weekly_point(
        source,
        "2020-02-28",
        target_root=tmp_path / "lake",
        staging_root=tmp_path / "stage",
        worker=None,
        code_list_path=str(codes)
        if source is StockWeeklySource.ALTERNATE_WEEKLY
        else None,
        fetch=lambda *args: frame_for(source),
    )
    path = Path(result["audit_path"])
    refs = [{"path": str(path), "sha256": fingerprint(path)}]
    entries = audit_weekly_event_files(refs)
    assert len(entries) == 1 and entries[0]["rows"] == 1
    with pytest.raises(WeeklyCaptureError, match="event_audit_year_duplicate_or_empty"):
        audit_weekly_event_files(refs + refs)
    Path(result["path"]).write_bytes(b"corrupt")
    with pytest.raises(WeeklyCaptureError, match="event_formal_identity_mismatch"):
        audit_weekly_event_files(refs)


def test_existing_instance_configuration_rejects_redirects(tmp_path, monkeypatch):
    import yaml

    home = tmp_path / "instance"
    home.mkdir()
    artifact = tmp_path / "artifacts"
    artifact.mkdir()
    monkeypatch.setattr(adapter, "INSTANCE_HOME", home)
    config = {
        "storage": {
            "postgres": {
                "postgres_url": "postgresql://offline:secret@127.0.0.1:5432/offline"
            }
        },
        "local_artifact_storage": {
            "module": "dagster._core.storage.root",
            "class": "LocalArtifactStorage",
            "config": {"base_dir": str(artifact)},
        },
    }
    path = home / "dagster.yaml"
    path.write_text(yaml.safe_dump(config))
    _, _, identity = adapter._configuration(home)
    assert "secret" not in json.dumps(identity)
    config["instance_class"] = {"module": "malicious"}
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(WeeklyCaptureError, match="unsupported_instance_configuration"):
        adapter._configuration(home)


def test_instance_autocreate_is_always_disabled_and_identity_freezes(
    tmp_path, monkeypatch
):
    calls = []
    root = tmp_path / "artifacts"
    root.mkdir()
    identity = {"offline": True}
    monkeypatch.setattr(
        adapter, "_configuration", lambda home: ("postgresql://offline", root, identity)
    )

    class Store:
        def __init__(self, url, *, should_autocreate_tables):
            calls.append(should_autocreate_tables)

        def dispose(self):
            pass

    for name in (
        "PostgresRunStorage",
        "PostgresEventLogStorage",
        "PostgresScheduleStorage",
    ):
        monkeypatch.setattr(adapter, name, Store)
    monkeypatch.setattr(adapter.dg, "DagsterInstance", lambda **kwargs: kwargs)
    with adapter.open_weekly_event_instance(identity=identity) as (instance, actual):
        assert actual == identity
        assert instance["run_launcher"] is None
    assert calls == [False, False, False]
    with (
        pytest.raises(WeeklyCaptureError, match="instance_identity_changed"),
        adapter.open_weekly_event_instance(identity={"changed": True}),
    ):
        pass
    assert calls == [False, False, False]
