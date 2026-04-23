from __future__ import annotations

from types import SimpleNamespace

from src.foundation.services.sync_v2.runtime_registry import build_sync_service


def test_build_sync_service_builds_v2_service_from_contract(mocker) -> None:
    session = mocker.Mock()
    settings = SimpleNamespace(sync_v2_strict_contract=False)
    mocker.patch("src.foundation.services.sync_v2.runtime_registry.get_settings", return_value=settings)
    contract = mocker.Mock()
    mocker.patch("src.foundation.services.sync_v2.runtime_registry.get_sync_v2_contract", return_value=contract)
    expected_service = mocker.Mock()
    ctor = mocker.patch("src.foundation.services.sync_v2.runtime_registry.SyncV2Service", return_value=expected_service)

    service = build_sync_service("trade_cal", session)

    assert service is expected_service
    ctor.assert_called_once_with(
        session,
        contract=contract,
        strict_contract=False,
    )


def test_build_sync_service_raises_when_contract_missing(mocker) -> None:
    session = mocker.Mock()
    settings = SimpleNamespace(sync_v2_strict_contract=True)
    mocker.patch("src.foundation.services.sync_v2.runtime_registry.get_settings", return_value=settings)
    mocker.patch("src.foundation.services.sync_v2.runtime_registry.get_sync_v2_contract", side_effect=KeyError("dummy"))
    v2_ctor = mocker.patch("src.foundation.services.sync_v2.runtime_registry.SyncV2Service")

    try:
        build_sync_service("dummy", session)
    except KeyError as exc:
        assert "dummy" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected KeyError")

    v2_ctor.assert_not_called()
