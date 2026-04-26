from src.scripts.repair_holdernumber_hashes import repair_holdernumber_hashes_with_connection


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


def test_repair_holdernumber_hashes_updates_raw_and_core(mocker) -> None:
    connection = mocker.Mock()
    raw_rows = [{"id": 1, "ts_code": "000001.SZ", "ann_date": None, "end_date": "1996-12-31", "holder_num": 330500}]
    core_rows = [{"id": 2, "ts_code": "000001.SZ", "ann_date": None, "end_date": "1996-12-31", "holder_num": 330500}]
    connection.execute.side_effect = [
        _Result(raw_rows),
        mocker.Mock(),
        _Result(core_rows),
        mocker.Mock(),
    ]

    summary = repair_holdernumber_hashes_with_connection(connection)

    assert summary.raw_scanned == 1
    assert summary.raw_updated == 1
    assert summary.raw_deleted == 0
    assert summary.core_scanned == 1
    assert summary.core_updated == 1
    assert summary.core_deleted == 0
