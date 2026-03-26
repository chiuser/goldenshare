from __future__ import annotations

from datetime import date

from src.dao.index_weight_dao import IndexWeightDAO
from src.dao.stk_period_bar_dao import StkPeriodBarDAO


def test_stk_period_bar_dao_get_bars_orders_by_trade_date(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = iter([mocker.Mock(), mocker.Mock()])
    dao = StkPeriodBarDAO(session)

    rows = dao.get_bars("000001.SZ", "week", date(2026, 1, 1), date(2026, 3, 31))

    assert len(rows) == 2
    session.scalars.assert_called_once()


def test_index_weight_dao_get_latest_weights_returns_empty_when_no_latest_date(mocker) -> None:
    session = mocker.Mock()
    session.scalar.return_value = None
    dao = IndexWeightDAO(session)

    rows = dao.get_latest_weights("000300.SH", date(2026, 3, 31))

    assert rows == []
    session.scalar.assert_called_once()


def test_index_weight_dao_get_latest_weights_loads_latest_batch(mocker) -> None:
    session = mocker.Mock()
    session.scalar.return_value = date(2026, 3, 31)
    session.scalars.return_value = iter([mocker.Mock(con_code="000001.SZ"), mocker.Mock(con_code="000002.SZ")])
    dao = IndexWeightDAO(session)

    rows = dao.get_latest_weights("000300.SH", date(2026, 3, 31))

    assert len(rows) == 2
    assert session.scalar.call_count == 1
    assert session.scalars.call_count == 1
