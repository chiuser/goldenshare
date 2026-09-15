"""Bounded merge pagination cannot turn one visible page into the whole-day total."""
from types import SimpleNamespace

from src.biz.queries.wealth.market.trading_assistant.return_contributions import contribution_page
from src.biz.services.wealth.market.trading_assistant.calculation.returns import profit_result


class Budget:
    def remaining_ms(self):
        return 5000


def part(code, profit, capital):
    return code, SimpleNamespace(result=profit_result(profit, capital, participates=True)), "Ready", None, None


def test_complete_merge_total_across_pages_and_accounts():
    streams = lambda: [iter([part(f"{i:06}.SZ", i, 10000) for i in range(30)]),
                       iter([part("000001.SZ", 100, 20000)])]
    rows, count, total, more = contribution_page(streams(), after=None, limit=20, deadline=Budget())
    assert (len(rows), count, total, more) == (20, 30, 535, True)
    assert (rows[1]["profitAmount"], rows[1]["capitalAmount"], rows[1]["returnPct"]) == ("1.01", "300.00", "0.34")
    tail, count2, total2, more2 = contribution_page(streams(), after=rows[-1]["code"], limit=20, deadline=Budget())
    assert (len(tail), count2, total2, more2) == (10, 30, 535, False)
    assert len({row["code"] for row in rows + tail}) == 30


def test_missing_same_stock_does_not_publish_known_subtotal_as_complete():
    rows, count, total, more = contribution_page([
        iter([part("000001.SZ", 0, 10000)]), iter([("000001.SZ", None, "Delayed", "缺行情", None)])],
        after=None, limit=20, deadline=Budget())
    assert (count, total, more) == (1, None, False)
    assert rows[0]["dataStatus"] == "Partial" and rows[0]["profitAmount"] is None


def test_empty_and_real_zero_are_distinct():
    assert contribution_page([], after=None, limit=20, deadline=Budget()) == ([], 0, 0, False)
    rows, count, total, more = contribution_page([iter([part("000001.SZ", 0, 100)])],
        after=None, limit=20, deadline=Budget())
    assert rows[0]["profitAmount"] == "0.00" and rows[0]["returnPct"] == "0.00"
