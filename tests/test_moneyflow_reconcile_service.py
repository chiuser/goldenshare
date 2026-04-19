from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.ops.services.operations_moneyflow_reconcile_service import MoneyflowReconcileService


def _tushare_row(
    ts_code: str,
    trade_date: date,
    *,
    buy_sm: str,
    buy_md: str,
    buy_lg: str,
    buy_elg: str,
    sell_sm: str,
    sell_md: str,
    sell_lg: str,
    sell_elg: str,
) -> SimpleNamespace:
    net = (
        Decimal(buy_sm)
        + Decimal(buy_md)
        + Decimal(buy_lg)
        + Decimal(buy_elg)
        - Decimal(sell_sm)
        - Decimal(sell_md)
        - Decimal(sell_lg)
        - Decimal(sell_elg)
    )
    return SimpleNamespace(
        ts_code=ts_code,
        trade_date=trade_date,
        buy_sm_amount=Decimal(buy_sm),
        buy_md_amount=Decimal(buy_md),
        buy_lg_amount=Decimal(buy_lg),
        buy_elg_amount=Decimal(buy_elg),
        sell_sm_amount=Decimal(sell_sm),
        sell_md_amount=Decimal(sell_md),
        sell_lg_amount=Decimal(sell_lg),
        sell_elg_amount=Decimal(sell_elg),
        net_mf_amount=net,
    )


def _biying_row(
    dm: str,
    trade_date: date,
    *,
    buy_sm: str,
    buy_md: str,
    buy_lg: str,
    buy_elg: str,
    sell_sm: str,
    sell_md: str,
    sell_lg: str,
    sell_elg: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        dm=dm,
        trade_date=trade_date,
        zmbxdcje=Decimal(buy_sm),
        zmbzdcje=Decimal(buy_md),
        zmbddcje=Decimal(buy_lg),
        zmbtdcje=Decimal(buy_elg),
        zmsxdcje=Decimal(sell_sm),
        zmszdcje=Decimal(sell_md),
        zmsddcje=Decimal(sell_lg),
        zmstdcje=Decimal(sell_elg),
    )


def test_moneyflow_reconcile_service_counts_and_diffs(mocker) -> None:
    session = mocker.Mock()
    session.scalars.side_effect = [
        [
            _tushare_row(
                "000001.SZ",
                date(2026, 4, 10),
                buy_sm="10",
                buy_md="20",
                buy_lg="30",
                buy_elg="40",
                sell_sm="5",
                sell_md="10",
                sell_lg="20",
                sell_elg="30",
            ),
            _tushare_row(
                "000002.SZ",
                date(2026, 4, 10),
                buy_sm="10",
                buy_md="20",
                buy_lg="30",
                buy_elg="40",
                sell_sm="5",
                sell_md="10",
                sell_lg="20",
                sell_elg="30",
            ),
            _tushare_row(
                "000003.SZ",
                date(2026, 4, 10),
                buy_sm="100",
                buy_md="200",
                buy_lg="300",
                buy_elg="400",
                sell_sm="50",
                sell_md="100",
                sell_lg="200",
                sell_elg="300",
            ),
        ],
        [
            _biying_row(
                "000001.SZ",
                date(2026, 4, 10),
                buy_sm="10",
                buy_md="20",
                buy_lg="30",
                buy_elg="40",
                sell_sm="5",
                sell_md="10",
                sell_lg="20",
                sell_elg="30",
            ),
            _biying_row(
                "000003.SZ",
                date(2026, 4, 10),
                buy_sm="150",
                buy_md="200",
                buy_lg="300",
                buy_elg="400",
                sell_sm="50",
                sell_md="100",
                sell_lg="200",
                sell_elg="300",
            ),
            _biying_row(
                "000004.SZ",
                date(2026, 4, 10),
                buy_sm="10",
                buy_md="20",
                buy_lg="30",
                buy_elg="40",
                sell_sm="5",
                sell_md="10",
                sell_lg="20",
                sell_elg="30",
            ),
        ],
    ]

    report = MoneyflowReconcileService().run(
        session,
        start_date=date(2026, 4, 10),
        end_date=date(2026, 4, 10),
        sample_limit=10,
        abs_tol=Decimal("1"),
        rel_tol=Decimal("0.03"),
    )

    assert report.total_union == 4
    assert report.comparable == 2
    assert report.only_tushare == 1
    assert report.only_biying == 1
    assert report.comparable_diff == 1
    assert report.direction_mismatch == 0
    assert report.samples["only_tushare"][0].ts_code == "000002.SZ"
    assert report.samples["only_biying"][0].ts_code == "000004.SZ"
    assert report.samples["comparable_diff"][0].ts_code == "000003.SZ"
    assert report.samples["comparable_diff"][0].field == "buy_sm_amount"


def test_moneyflow_reconcile_service_normalizes_dm_without_suffix(mocker) -> None:
    session = mocker.Mock()
    session.scalars.side_effect = [
        [
            _tushare_row(
                "600001.SH",
                date(2026, 4, 10),
                buy_sm="10",
                buy_md="20",
                buy_lg="30",
                buy_elg="40",
                sell_sm="5",
                sell_md="10",
                sell_lg="20",
                sell_elg="30",
            ),
        ],
        [
            _biying_row(
                "600001",
                date(2026, 4, 10),
                buy_sm="10",
                buy_md="20",
                buy_lg="30",
                buy_elg="40",
                sell_sm="5",
                sell_md="10",
                sell_lg="20",
                sell_elg="30",
            ),
        ],
    ]

    report = MoneyflowReconcileService().run(
        session,
        start_date=date(2026, 4, 10),
        end_date=date(2026, 4, 10),
        sample_limit=0,
    )

    assert report.total_union == 1
    assert report.comparable == 1
    assert report.comparable_diff == 0
