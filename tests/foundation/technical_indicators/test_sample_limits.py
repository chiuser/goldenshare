"""LLD 19.8 diagnostic limits, independently specified literal metadata.

No real file, connection, thread or dataset is accessed. Metadata/reader
substitutes verify that rejection happens before opening the data reader.
"""

from types import SimpleNamespace

import pyarrow as pa
import pytest

from scripts.diagnostics import technical_indicator_d2_acceptance as diagnostic


@pytest.mark.parametrize('rows,allowed', [(32768,True),(262144,False),(32767,False),(0,False)])
def test_exact_footer_rows_are_checked_before_creating_any_data_reader(monkeypatch,rows,allowed):
    calls=[]
    monkeypatch.setattr(diagnostic,'inspect_fixture',lambda path:dict(rows=rows,bytes=386178,projected_row_group_bytes=196608))
    monkeypatch.setattr(diagnostic,'create_fixture_reader',lambda path:calls.append(path) or 'reader')
    if allowed:
        assert diagnostic.open_checked_fixture('named-sample')[1]=='reader'
        assert calls==['named-sample']
    else:
        with pytest.raises(ValueError,match='exactly 32768'):
            diagnostic.open_checked_fixture('named-sample')
        assert calls==[]


@pytest.mark.parametrize('key,limit', [('bytes',8388608),('projected_row_group_bytes',33554432)])
def test_metadata_resource_boundary_has_a_normal_and_rejected_side(key,limit):
    values=dict(rows=32768,bytes=386178,projected_row_group_bytes=196608)
    values[key]=limit
    diagnostic.validate_fixture(values)
    with pytest.raises(ValueError):
        diagnostic.validate_fixture(values|{key:limit+1})


@pytest.mark.parametrize('rows,batches,size',[ (32768,4,1),(32760,3,9),(0,0,8193)])
def test_oversized_or_extra_batches_are_never_delivered(rows,batches,size):
    # The i values themselves do not matter: size/batch limits must reject first.
    batch=pa.record_batch([pa.array([0]*size)],names=['i'])
    guard=diagnostic.CheckedReader(SimpleNamespace(read_next_batch=lambda:batch))
    guard.rows,guard.batches=rows,batches
    with pytest.raises(ValueError,match='budget'):
        guard.read_next_batch()
    assert (guard.rows,guard.batches)==(rows,batches)


def test_legal_partial_last_batch_and_real_eof_are_preserved():
    values=iter((pa.record_batch([pa.array([32766,32767])],names=['i']),))
    guard=diagnostic.CheckedReader(SimpleNamespace(read_next_batch=lambda:next(values)))
    guard.rows,guard.batches=32766,3
    assert guard.read_next_batch().num_rows==2
    assert (guard.rows,guard.batches)==(32768,4)
    with pytest.raises(StopIteration):
        guard.read_next_batch()
