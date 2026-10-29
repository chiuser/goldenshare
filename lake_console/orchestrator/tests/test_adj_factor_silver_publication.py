"""Real three-column Raw and ten-column lifecycle fixtures, LLD 25.2/25.7."""

import json
from pathlib import Path
from uuid import uuid4

import duckdb
import pytest

import orchestrator.defs.assets.adj_factor as asset_module
import orchestrator.defs.checks.adj_factor_checks as check_module
import orchestrator.defs.io.adj_factor_silver_publication as publication
from orchestrator.defs.assets.adj_factor import write_silver_adj_factor_partition
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_adj_factor_publication_root,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.resources import DuckDBResource

DAY = "2026-10-28"
OLD = "2026-10-22"
RESTORE = [{"ts_code": "301139.SZ", "trade_date": OLD}]


@pytest.fixture(autouse=True)
def isolated_duckdb(tmp_path, monkeypatch):
    """Only relocate real DuckDB spill files; retain production SQL/settings."""
    settings = DuckDBConnectionSettings(temp_directory=tmp_path / 'duckdb')

    def connect():
        return connect_configured_duckdb(settings)

    monkeypatch.setattr(asset_module, 'connect_configured_duckdb', connect)
    monkeypatch.setattr(check_module, 'connect_configured_duckdb', connect)


def _copy(con, sql, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({sql}) TO '{path}' (FORMAT PARQUET)")


@pytest.fixture
def data(tmp_path):
    root, staging = tmp_path / "lake", tmp_path / "stage"
    root.mkdir()
    staging.mkdir()
    life = silver_stock_lifecycle_path(root)
    # Columns/types come from the real lifecycle producer's ten-column contract.
    with duckdb.connect(":memory:") as con:
        _copy(con, """SELECT ts_code,symbol,name,exchange,market,curr_type,is_cny_stock,
            list_status,CAST(list_date AS DATE) list_date,CAST(delist_date AS DATE) delist_date
            FROM (VALUES
              ('000001.SZ','000001','平安','SZSE','主板','CNY',true,'L','1991-04-03',NULL),
              ('301139.SZ','301139','元道','SZSE','创业板','CNY',true,'D','2022-07-08','2026-10-28'),
              ('600002.SH','600002','历史退市','SSE','主板','CNY',true,'D','1990-01-01','2020-01-01')
            ) t(ts_code,symbol,name,exchange,market,curr_type,is_cny_stock,
                list_status,list_date,delist_date)""", life)
        for day in (OLD, DAY):
            value = "1.0079" if day == OLD else "1.1319"
            _copy(con, f"""SELECT ts_code,'{day.replace('-', '')}'::VARCHAR trade_date,
                  adj_factor::DOUBLE adj_factor FROM (VALUES
                  ('000001.SZ',1.5),('301139.SZ',{value}),('600002.SH',2.0)) t(ts_code,adj_factor)""",
                  raw_adj_factor_path(root, day))
        _copy(con, f"SELECT '000001.SZ'::VARCHAR ts_code,DATE '{OLD}' trade_date,1.5::DOUBLE adj_factor",
              silver_adj_factor_path(root, OLD))
        assert con.execute("DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)", [str(raw_adj_factor_path(root, OLD))]).fetchall()[:3] == [
            ('ts_code','VARCHAR','YES',None,None,None),
            ('trade_date','VARCHAR','YES',None,None,None),
            ('adj_factor','DOUBLE','YES',None,None,None),
        ]
    return root, staging


def _write(data, *, day=DAY, pub=None, keys=(), **kwargs):
    root, staging = data
    return write_silver_adj_factor_partition(
        lake_root=root, duckdb=DuckDBResource(), partition_key=day,
        publication_id=pub or str(uuid4()), staging_root=staging,
        restore_missing_keys=keys, overwrite=True, **kwargs,
    )


def _rows(root, day):
    with duckdb.connect(":memory:") as con:
        return con.execute("SELECT ts_code,adj_factor FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                           [str(silver_adj_factor_path(root, day))]).fetchall()


def test_new_day_keeps_source_retired_records_including_after_delist(data):
    root, _ = data
    raw = raw_adj_factor_path(root, DAY).read_bytes()
    result = _write(data)
    assert _rows(root, DAY) == [('000001.SZ',1.5),('301139.SZ',1.1319),('600002.SH',2.0)]
    assert result.row_count == 3 and result.restored_row_count == 0
    assert raw_adj_factor_path(root, DAY).read_bytes() == raw
    assert not list(root.rglob('*.tmp'))


def test_old_day_inserts_only_explicit_key_and_replay_is_noop(data):
    root, _ = data
    first = _write(data, day=OLD, keys=RESTORE)
    assert first.restored_row_count == 1
    assert first.source_eligible_row_count == 3
    assert first.selected_row_count == 1 and first.preserved_row_count == 1
    assert first.rejected_row_count == 2 and first.write_mode == 'restore_missing_keys'
    assert _rows(root, OLD) == [('000001.SZ',1.5),('301139.SZ',1.0079)]
    before = publication.file_identity(silver_adj_factor_path(root, OLD))
    replay = _write(data, day=OLD, keys=RESTORE)
    assert replay.unchanged and replay.restored_row_count == 0
    assert publication.file_identity(silver_adj_factor_path(root, OLD)) == before


@pytest.mark.parametrize('day,keys',[
    (OLD, []), (OLD,[{'ts_code':'301139.SZ','trade_date':'2026-10-21'}]),
    (DAY,RESTORE), (OLD,RESTORE*2),
    (OLD,[{'ts_code':'bad','trade_date':OLD}]),
    (OLD,[{'ts_code':'301139.SZ','trade_date':'2026-02-30'}]),
])
def test_restore_configuration_rejects_wrong_scope_without_writes(data, day, keys):
    root, staging = data
    before = silver_adj_factor_path(root, OLD).read_bytes()
    with pytest.raises(ValueError):
        _write(data, day=day, keys=keys)
    assert silver_adj_factor_path(root, OLD).read_bytes() == before
    assert list(staging.iterdir()) == []


def test_restore_different_existing_value_is_rejected(data):
    root, _ = data
    target = silver_adj_factor_path(root, OLD)
    with duckdb.connect(":memory:") as con:
        _copy(con, f"SELECT '000001.SZ' ts_code,DATE '{OLD}' trade_date,1.5::DOUBLE adj_factor UNION ALL SELECT '301139.SZ',DATE '{OLD}',9.0::DOUBLE", target)
    before = target.read_bytes()
    with pytest.raises(ValueError, match='existing_value_differs'):
        _write(data, day=OLD, keys=RESTORE)
    assert target.read_bytes() == before


def test_missing_source_key_is_rejected(data):
    root, _ = data
    before = silver_adj_factor_path(root, OLD).read_bytes()
    keys = [{'ts_code':'600003.SH','trade_date':OLD}]
    with pytest.raises(ValueError, match='source_missing_or_identity_invalid'):
        _write(data, day=OLD, keys=keys)
    assert silver_adj_factor_path(root, OLD).read_bytes() == before


def test_candidate_failure_preserves_original_and_failure_candidate(data):
    root, staging = data
    raw = raw_adj_factor_path(root, DAY)
    with duckdb.connect(":memory:") as con:
        _copy(con, "SELECT '301139.SZ' ts_code,'20261028' trade_date,1.1319::DOUBLE adj_factor", raw)
    with pytest.raises(ValueError, match='candidate_rules_failed'):
        _write(data)
    assert not silver_adj_factor_path(root, DAY).exists()
    assert len(list(staging.rglob('candidate-0.parquet'))) == 1


def test_replace_success_receipt_failure_recovers_before_old_input_guard(data, monkeypatch):
    root, staging = data
    pub = str(uuid4())
    real = publication._checkpoint

    def fail_commit(path, state):
        if state['phase'] == 'committed':
            raise OSError('simulated commit receipt failure')
        real(path, state)

    monkeypatch.setattr(publication, '_checkpoint', fail_commit)
    with pytest.raises(OSError, match='receipt failure'):
        _write(data, day=OLD, keys=RESTORE, pub=pub)
    target = silver_adj_factor_path(root, OLD)
    published = publication.file_identity(target)
    control = silver_adj_factor_publication_root(staging, pub, OLD) / 'publication.json'
    assert json.loads(control.read_text())['phase'] == 'prepared'
    assert _rows(root, OLD) == [('000001.SZ',1.5),('301139.SZ',1.0079)]
    monkeypatch.setattr(publication, '_checkpoint', real)

    def forbid_recompute(*args, **kwargs):
        raise AssertionError('completed candidate must not be rebuilt')

    monkeypatch.setattr(asset_module, 'build_silver_adj_factor_candidate', forbid_recompute)
    result = _write(data, day=OLD, keys=RESTORE, pub=pub)
    assert result.restored_row_count == 1
    assert publication.file_identity(target) == published
    assert json.loads(control.read_text())['phase'] == 'committed'


def test_source_change_before_replace_is_rejected(data, monkeypatch):
    root, _ = data
    before = silver_adj_factor_path(root, OLD).read_bytes()
    real = asset_module.build_silver_adj_factor_candidate

    def change_source(*args, **kwargs):
        result = real(*args, **kwargs)
        raw = raw_adj_factor_path(root, OLD)
        raw.touch()
        return result

    monkeypatch.setattr(asset_module, 'build_silver_adj_factor_candidate', change_source)
    with pytest.raises(ValueError, match='source_changed'):
        _write(data, day=OLD, keys=RESTORE)
    assert silver_adj_factor_path(root, OLD).read_bytes() == before


def test_same_execution_cannot_change_authorized_keys(data):
    pub = str(uuid4())
    _write(data, day=OLD, keys=RESTORE, pub=pub)
    with pytest.raises(ValueError, match='publication_binding'):
        _write(data, day=OLD, pub=pub, keys=[{'ts_code':'600002.SH','trade_date':OLD}])


@pytest.mark.parametrize('sql', [
    f"SELECT '000001.SZ' ts_code,DATE '{OLD}' trade_date,1::INTEGER adj_factor",
    f"SELECT '000001.SZ' ts_code,'{OLD}'::VARCHAR trade_date,1.5::DOUBLE adj_factor",
    f"SELECT '000001.SZ' ts_code,DATE '{OLD}' trade_date,1.5::DOUBLE adj_factor,1 extra",
])
def test_old_schema_is_not_silently_coerced_or_projected(data, sql):
    root, _ = data
    target = silver_adj_factor_path(root, OLD)
    with duckdb.connect(':memory:') as con:
        _copy(con, sql, target)
    before = target.read_bytes()
    with pytest.raises(ValueError, match='restore_existing_schema'):
        _write(data, day=OLD, keys=RESTORE)
    assert target.read_bytes() == before


@pytest.mark.parametrize('unchanged', [False, True])
def test_source_changes_during_commit_stop_without_reverting_target(data, monkeypatch, unchanged):
    root, staging = data
    if unchanged:
        _write(data, day=OLD, keys=RESTORE)
    pub = str(uuid4())
    checkpoint = publication._checkpoint

    def change_source_at_commit(path, state):
        checkpoint(path, state)
        if state['phase'] == 'committed':
            raw_adj_factor_path(root, OLD).touch()

    monkeypatch.setattr(publication, '_checkpoint', change_source_at_commit)
    with pytest.raises(ValueError, match='source_changed'):
        _write(data, day=OLD, keys=RESTORE, pub=pub)
    assert _rows(root, OLD) == [('000001.SZ',1.5),('301139.SZ',1.0079)]
    control = silver_adj_factor_publication_root(staging, pub, OLD) / 'publication.json'
    assert json.loads(control.read_text())['phase'] == 'committed'


def test_prepared_interrupt_resumes_candidate_without_rebuilding(data, monkeypatch):
    root, _ = data
    pub = str(uuid4())
    target = silver_adj_factor_path(root, OLD)
    before = target.read_bytes()
    replace = publication.os.replace

    def fail_promotion(source, destination):
        if Path(destination) == target:
            raise OSError('simulated interruption before promotion')
        replace(source, destination)

    monkeypatch.setattr(publication.os, 'replace', fail_promotion)
    with pytest.raises(OSError, match='before promotion'):
        _write(data, day=OLD, keys=RESTORE, pub=pub)
    assert target.read_bytes() == before
    monkeypatch.setattr(publication.os, 'replace', replace)
    monkeypatch.setattr(asset_module, 'build_silver_adj_factor_candidate',
                        lambda *a, **k: pytest.fail('prepared candidate must be reused'))
    _write(data, day=OLD, keys=RESTORE, pub=pub)
    assert _rows(root, OLD) == [('000001.SZ',1.5),('301139.SZ',1.0079)]


def test_concurrent_writer_is_rejected(data):
    import fcntl

    _, staging = data
    locks = staging / 'adj_factor/silver/locks'
    locks.mkdir(parents=True)
    with (locks / f'trade_date={OLD}.lock').open('a+') as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='writer_busy'):
            _write(data, day=OLD, keys=RESTORE)


def test_target_change_after_candidate_is_not_overwritten(data, monkeypatch):
    root, _ = data
    target = silver_adj_factor_path(root, OLD)
    original = target.read_bytes()
    build = asset_module.build_silver_adj_factor_candidate

    def change_target(*args, **kwargs):
        result = build(*args, **kwargs)
        target.touch()
        return result

    monkeypatch.setattr(asset_module, 'build_silver_adj_factor_candidate', change_target)
    with pytest.raises(ValueError, match='target_changed'):
        _write(data, day=OLD, keys=RESTORE)
    assert target.read_bytes() == original
