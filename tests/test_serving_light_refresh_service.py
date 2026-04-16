from __future__ import annotations

from types import SimpleNamespace

from src.operations.services.serving_light_refresh_service import ServingLightRefreshService


def test_refresh_equity_daily_bar_without_optional_filters(mocker) -> None:
    session = mocker.Mock()
    session.execute.return_value = SimpleNamespace(rowcount=10)

    result = ServingLightRefreshService().refresh_equity_daily_bar(session)

    assert result.touched_rows == 10
    session.execute.assert_called_once()
    stmt, params = session.execute.call_args.args
    assert "WHERE 1=1" in str(stmt)
    assert params == {}
    session.commit.assert_called_once()

