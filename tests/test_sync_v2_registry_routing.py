from __future__ import annotations

from types import SimpleNamespace

from src.foundation.services.sync.registry import SYNC_SERVICE_REGISTRY, build_sync_service


def test_build_sync_service_routes_to_v2_when_dataset_enabled(mocker) -> None:
    session = mocker.Mock()
    settings = SimpleNamespace(use_sync_v2_datasets="trade_cal,margin", sync_v2_strict_contract=False)
    mocker.patch("src.foundation.services.sync.registry.get_settings", return_value=settings)
    mocker.patch("src.foundation.services.sync.registry.has_sync_v2_contract", return_value=True)
    contract = mocker.Mock()
    mocker.patch("src.foundation.services.sync.registry.get_sync_v2_contract", return_value=contract)
    expected_service = mocker.Mock()
    ctor = mocker.patch("src.foundation.services.sync.registry.SyncV2Service", return_value=expected_service)

    service = build_sync_service("trade_cal", session)

    assert service is expected_service
    ctor.assert_called_once_with(
        session,
        contract=contract,
        strict_contract=False,
    )


def test_build_sync_service_falls_back_to_v1_when_contract_missing(mocker) -> None:
    class _DummyService:
        def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
            self.session = session

    session = mocker.Mock()
    settings = SimpleNamespace(use_sync_v2_datasets="dummy", sync_v2_strict_contract=True)
    mocker.patch("src.foundation.services.sync.registry.get_settings", return_value=settings)
    mocker.patch("src.foundation.services.sync.registry.has_sync_v2_contract", return_value=False)
    v2_ctor = mocker.patch("src.foundation.services.sync.registry.SyncV2Service")
    mocker.patch.dict(SYNC_SERVICE_REGISTRY, {"dummy": _DummyService}, clear=False)

    service = build_sync_service("dummy", session)

    assert isinstance(service, _DummyService)
    assert service.session is session
    v2_ctor.assert_not_called()
