from src.scripts.repair_dividend_hashes import repair_dividend_hashes_with_connection


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


def test_repair_dividend_hashes_updates_raw_and_core(mocker) -> None:
    connection = mocker.Mock()
    raw_rows = [
        {
            "id": 1,
            "ts_code": "000001.SZ",
            "end_date": "2025-12-31",
            "ann_date": "2026-03-21",
            "div_proc": "预案",
            "stk_div": None,
            "stk_bo_rate": None,
            "stk_co_rate": None,
            "cash_div": None,
            "cash_div_tax": None,
            "record_date": None,
            "ex_date": None,
            "pay_date": None,
            "div_listdate": None,
            "imp_ann_date": None,
            "base_date": None,
            "base_share": None,
        }
    ]
    core_rows = [
        {
            "id": 2,
            "ts_code": "000001.SZ",
            "end_date": "2025-12-31",
            "ann_date": "2026-03-21",
            "div_proc": "预案",
            "stk_div": None,
            "stk_bo_rate": None,
            "stk_co_rate": None,
            "cash_div": None,
            "cash_div_tax": None,
            "record_date": None,
            "ex_date": None,
            "pay_date": None,
            "div_listdate": None,
            "imp_ann_date": None,
            "base_date": None,
            "base_share": None,
        }
    ]
    connection.execute.side_effect = [
        _Result(raw_rows),
        mocker.Mock(),
        _Result(core_rows),
        mocker.Mock(),
    ]

    summary = repair_dividend_hashes_with_connection(connection)

    assert summary.raw_scanned == 1
    assert summary.raw_updated == 1
    assert summary.raw_deleted == 0
    assert summary.core_scanned == 1
    assert summary.core_updated == 1
    assert summary.core_deleted == 0


def test_repair_dividend_hashes_dedupes_duplicate_row_hashes(mocker) -> None:
    connection = mocker.Mock()
    duplicate_row = {
        "ts_code": "000001.SZ",
        "end_date": "2025-12-31",
        "ann_date": "2026-03-21",
        "div_proc": "预案",
        "stk_div": None,
        "stk_bo_rate": None,
        "stk_co_rate": None,
        "cash_div": None,
        "cash_div_tax": None,
        "record_date": None,
        "ex_date": None,
        "pay_date": None,
        "div_listdate": None,
        "imp_ann_date": None,
        "base_date": None,
        "base_share": None,
    }
    raw_rows = [{**duplicate_row, "id": 1}, {**duplicate_row, "id": 2}]
    core_rows = [{**duplicate_row, "id": 3}, {**duplicate_row, "id": 4}]
    connection.execute.side_effect = [
        _Result(raw_rows),
        mocker.Mock(),
        mocker.Mock(),
        _Result(core_rows),
        mocker.Mock(),
        mocker.Mock(),
    ]

    summary = repair_dividend_hashes_with_connection(connection)

    assert summary.raw_deleted == 1
    assert summary.core_deleted == 1
