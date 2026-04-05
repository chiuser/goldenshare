from __future__ import annotations

from datetime import date

from src.foundation.dao.factory import DAOFactory
from src.foundation.dao.etf_basic_dao import EtfBasicDAO
from src.foundation.dao.index_basic_dao import IndexBasicDAO
from src.foundation.dao.index_weight_dao import IndexWeightDAO
from src.foundation.dao.stk_period_bar_dao import StkPeriodBarDAO


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


def test_index_basic_dao_get_active_indexes_loads_rows(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = iter([mocker.Mock(ts_code="000001.SH"), mocker.Mock(ts_code="000300.SH")])
    dao = IndexBasicDAO(session)

    rows = dao.get_active_indexes()

    assert len(rows) == 2
    session.scalars.assert_called_once()


def test_dao_factory_exposes_etf_basic_daos(mocker) -> None:
    session = mocker.Mock()

    dao = DAOFactory(session)

    assert dao.raw_etf_basic.model.__name__ == "RawEtfBasic"
    assert isinstance(dao.etf_basic, EtfBasicDAO)


def test_etf_basic_dao_get_active_etfs_queries_supported_statuses(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = iter([mocker.Mock(ts_code="510300.SH"), mocker.Mock(ts_code="159915.SZ")])
    dao = EtfBasicDAO(session)

    rows = dao.get_active_etfs()

    assert len(rows) == 2
    session.scalars.assert_called_once()


def test_etf_basic_dao_get_fund_daily_candidates_excludes_of_suffix(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = iter([mocker.Mock(ts_code="510300.SH"), mocker.Mock(ts_code="159915.SZ")])
    dao = EtfBasicDAO(session)

    rows = dao.get_fund_daily_candidates()

    assert len(rows) == 2
    session.scalars.assert_called_once()
