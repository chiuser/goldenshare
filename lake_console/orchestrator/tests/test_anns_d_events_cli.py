"""Invalid scopes stop before IO; default plan uses only a readonly instance."""

from unittest.mock import Mock

import pytest

from orchestrator.defs.anns_d_checkpoint import AnnouncementControl
from orchestrator.defs.anns_d_contract import AnnouncementError
from orchestrator.defs.bootstrap import anns_d_events_cli as module


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--history-plan", "/private/tmp/missing"],
        ["--event-plan", "/private/tmp/x"],
        ["--fingerprint", "x"],
    ],
)
def test_plan_invalid_source_before_instance(tmp_path, monkeypatch, flags):
    opener = Mock()
    monkeypatch.setattr(module, "open_announcement_event_instance", opener)
    args = module.announcement_events_parser().parse_args(
        [*flags, "--report", str(tmp_path / "r.json")]
    )
    # Report restrictions are also checked before any connection.
    with pytest.raises(AnnouncementError):
        module.execute_announcement_events_cli(args, AnnouncementControl())
    opener.assert_not_called()


def test_apply_requires_explicit_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        module,
        "assert_safe_announcement_path",
        lambda _: __import__("pathlib").Path(
            "/private/tmp/not-existing-p4-test-report.json"
        ),
    )
    opener = Mock()
    monkeypatch.setattr(module, "open_announcement_event_instance", opener)
    args = module.announcement_events_parser().parse_args(
        [
            "checks",
            "--event-plan",
            str(tmp_path / "plan.json"),
            "--report",
            str(tmp_path / "r.json"),
        ]
    )
    with pytest.raises(AnnouncementError, match="frozen_plan_required"):
        module.execute_announcement_events_cli(args, AnnouncementControl())
    opener.assert_not_called()
