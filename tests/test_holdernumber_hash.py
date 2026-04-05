from src.foundation.services.transform.holdernumber_hash import build_holdernumber_event_key_hash, build_holdernumber_row_key_hash


def test_holdernumber_row_key_hash_changes_when_record_changes() -> None:
    base = {"ts_code": "000001.SZ", "ann_date": "1997-03-01", "end_date": "1996-12-31", "holder_num": 330500}
    revised = {**base, "holder_num": 330800}

    assert build_holdernumber_row_key_hash(base) != build_holdernumber_row_key_hash(revised)
    assert build_holdernumber_event_key_hash(base) == build_holdernumber_event_key_hash(revised)


def test_holdernumber_hash_treats_none_as_empty_string() -> None:
    row = {"ts_code": "000001.SZ", "ann_date": None, "end_date": "1996-12-31", "holder_num": 330500}

    assert len(build_holdernumber_row_key_hash(row)) == 64
    assert len(build_holdernumber_event_key_hash(row)) == 64
