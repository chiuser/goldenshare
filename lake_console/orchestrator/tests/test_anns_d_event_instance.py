"""Existing PostgreSQL only, enforced readonly defaults, no initialization."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from orchestrator.defs.anns_d_contract import AnnouncementError
from orchestrator.defs.bootstrap import anns_d_event_instance as module


@pytest.mark.parametrize("writable", [False, True])
def test_instance_no_autocreate_readonly_defaults(monkeypatch, tmp_path, writable):
    identity = {"fixture": True}
    monkeypatch.setattr(
        module,
        "_configuration",
        lambda _: (
            "postgresql://user:secret@localhost/goldenshare_dagster",
            tmp_path,
            identity,
        ),
    )
    run, event = Mock(), Mock()
    monkeypatch.setattr(module, "PostgresRunStorage", run)
    monkeypatch.setattr(module, "PostgresEventLogStorage", event)
    monkeypatch.setattr(module.dg, "DagsterInstance", Mock())
    with module.open_announcement_event_instance(identity=identity, writable=writable):
        pass
    for constructor in (run, event):
        url = constructor.call_args.args[0]
        assert constructor.call_args.kwargs == {"should_autocreate_tables": False}
        assert "statement_timeout" in url
        assert ("default_transaction_read_only" in url) is (not writable)
        constructor.return_value.dispose.assert_called_once()
    assert module.dg.DagsterInstance.call_args.kwargs["schedule_storage"] is None


def test_instance_identity_rejected_before_connect(monkeypatch):
    monkeypatch.setattr(
        module, "_configuration", lambda _: ("url", Path("/private/tmp"), {"old": 1})
    )
    constructor = Mock()
    monkeypatch.setattr(module, "PostgresRunStorage", constructor)
    with (
        pytest.raises(AnnouncementError, match="identity_changed"),
        module.open_announcement_event_instance(identity={"new": 1}),
    ):
        pass
    constructor.assert_not_called()
