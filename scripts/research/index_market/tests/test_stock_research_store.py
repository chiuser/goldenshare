from dataclasses import replace
import json
from zipfile import ZipFile
import pytest

from scripts.research.index_market.chan import stock_research_store as storage


def build(root):
    raw = b'{"value":1}'
    h = storage.digest(raw)
    with ZipFile(root/'evidence.zip', 'x') as z:
        z.writestr(h, raw)
    catalog = dict(version=1, sources={r:'historical/'+r for r in storage.SPEC.roles},
        records={k:dict(sha256=h, bytes=len(raw)) for k in ('initial/a.json','calendar/b.json')})
    (root/'catalog.json').write_text(json.dumps(catalog))
    receipt=dict(catalog_sha256=storage.digest((root/'catalog.json').read_bytes()),
                 archive_sha256=storage.digest((root/'evidence.zip').read_bytes()))
    (root/'storage_receipt.json').write_text(json.dumps(receipt))
    return storage.StockResearchStore(root), raw


def test_shared_object_and_no_extraction(tmp_path):
    store, raw = build(tmp_path)
    before = set(tmp_path.iterdir())
    assert store.blob('initial/a.json') == raw == store.blob('calendar/b.json')
    assert store.read('calendar/b.json') == {'value':1}
    with ZipFile(tmp_path/'evidence.zip') as z:
        assert len(z.namelist()) == 1
    assert set(tmp_path.iterdir()) == before
    store.verify_unchanged()


@pytest.mark.parametrize('key', ['../a', '/calendar/b.json', 'calendar/../a', 'unknown/a', 'calendar/missing'])
def test_bad_or_missing_key(tmp_path, key):
    store, _ = build(tmp_path)
    with pytest.raises(ValueError):
        store.read(key)


def test_original_manifest_hash_required(tmp_path):
    store, raw = build(tmp_path)
    assert store.blob('initial/a.json', storage.digest(raw)) == raw
    with pytest.raises(ValueError):
        store.read('initial/a.json', '0'*64)


@pytest.mark.parametrize('name', ['catalog.json', 'evidence.zip'])
def test_fingerprint_corruption(tmp_path, name):
    build(tmp_path)
    p = tmp_path/name
    p.write_bytes(p.read_bytes()+b'broken')
    with pytest.raises(ValueError):
        storage.StockResearchStore(tmp_path)


def test_bounds(tmp_path, monkeypatch):
    store, _ = build(tmp_path)
    monkeypatch.setattr(storage, 'SPEC', replace(storage.SPEC, record_bytes=1))
    with pytest.raises(ValueError):
        store.read('initial/a.json')
    monkeypatch.setattr(storage, 'SPEC', replace(storage.SPEC, archive_bytes=1))
    with pytest.raises(ValueError):
        storage.StockResearchStore(tmp_path)


def test_exact_code_migration_only(tmp_path):
    store, _ = build(tmp_path)
    p = tmp_path/'producer.py'
    p.write_text('old')
    before = storage.digest(p.read_bytes())
    store.verify_code(p, before)
    p.write_text('new')
    mapping = {str(p):dict(before=before, after=storage.digest(p.read_bytes()))}
    (tmp_path/'code_migration.json').write_text(json.dumps(mapping))
    store.verify_code(p, before)
    with pytest.raises(ValueError):
        store.verify_code(p, '0'*64)
    p.write_text('third version')
    with pytest.raises(ValueError):
        store.verify_code(p, before)


def test_runtime_change_rejected(tmp_path):
    store, _ = build(tmp_path)
    (tmp_path/'catalog.json').write_text('{}')
    with pytest.raises(ValueError):
        store.verify_unchanged()


def test_never_falls_back_to_filesystem(tmp_path):
    store, _ = build(tmp_path)
    (tmp_path/'calendar').mkdir()
    (tmp_path/'calendar/missing').write_text('{"value":2}')
    with pytest.raises(ValueError):
        store.read('calendar/missing')
