"""Name/source contract checks and shared isolated fixture for registered Web routes.

Former SQLite catalog-generation tests are replaced by test_announcement_direct_query.
The execution and query/preview controls use the same isolated PG fixture.
"""
import json
from pathlib import Path
from dataclasses import replace
import pytest
from test_announcement_pg_migration import pg,pg_cluster
from test_announcement_download_cli import archive,row as legacy_row
from test_announcement_download_dg import raw_root,make_source
from test_announcement_direct_query import write_names
from src.foundation.clients.announcement_archive.names import NameInitials
from src.foundation.clients.announcement_archive.volume import SourceVolume
from src.foundation.clients.announcement_archive.direct_source import DirectSource
from src.foundation.clients.announcement_archive.query_presence import QueryPresence
from src.foundation.config.announcement_archive import DataCenterPolicy
from src.foundation.dao.announcement_archive.pg_schema import install_schema
from src.foundation.dao.announcement_archive.pg_archive import register_archive
from src.foundation.dao.announcement_archive.query_controls import QueryControls
from src.ops.runtime.announcement_archive.source_runtime import SourcePreparation
from src.biz.services.wealth.data_center.query_service import AnnouncementQueryService
from src.biz.schemas.wealth.data_center.announcements import AnnouncementQueryRequest


def row(*args,**kwargs):
    extra={k:kwargs.pop(k) for k in ('name','rec_time','ts_code') if k in kwargs}
    result=legacy_row(*args,**kwargs);result.update(extra);return result


def request(**kw):return AnnouncementQueryRequest(startDate='2026-09-30',endDate='2026-09-30',**kw)


@pytest.fixture
def query_archive(archive,tmp_path,pg):
    raw_root(archive).mkdir(parents=True,exist_ok=True)
    legacy_source=make_source(archive,policy=replace(archive[3],batch_size=500))
    names_root=raw_root(archive).parent
    write_names(names_root,'stock_basic',('ts_code','name','cnspell'),[('000001.SZ','平安银行','PAYH'),('600000.SH','浦发银行','PFYH'),('000002.SZ','退市样本','TSYB')])
    write_names(names_root,'namechange',('ts_code','name'),[('000001.SZ','深发展A'),('000002.SZ','旧简称')])
    names_volume=SourceVolume(names_root,archive[3],archive[0].inspector).open()
    archive_volume=SourceVolume(archive[0].mount,archive[3],archive[0].inspector).open()
    source=DirectSource(legacy_source.volume,names_volume,archive[5],DataCenterPolicy())
    with pg.transaction() as conn:
        install_schema(conn);dao=register_archive(conn,archive[0].volume_uuid,archive[0].relative_root)
    controls=QueryControls(pg,dao.archive_id,source.scope)
    presence=QueryPresence(archive_volume,controls,archive[0].relative_root)
    service=AnnouncementQueryService(controls,source,presence)
    preparation=SourcePreparation(source,controls,presence,service.policy)
    # Fixture-only composition; Biz does not construct/import an Ops runtime.
    service.fixture_preparation=preparation
    yield service,archive,legacy_source
    preparation.close();source.close();presence.close();legacy_source.close()


def test_initials_normalization_dictionary_source_priority(tmp_path):
    convert=NameInitials()
    assert [convert(s) for s in ['平安银行','招商银行','深发展A','重庆银行','ST平安银行']]==['PAYH','ZSYH','SFZA','CQYH','STPAYH']
    assert convert('重-庆 银行','155162.SH','rawSpell')=='RAWSPELL'
    assert convert('ＳＴ平安银行')=='PAYH' # Non-ASCII symbols are excluded, not transliterated.
    path=tmp_path/'names.json';path.write_text(json.dumps({'version':2,'overrides':[{'name':'重庆银行','tsCode':'1.SH','initials':'TEST'}]}))
    changed=NameInitials(path)
    assert changed('重庆银行','1.SH')=='TEST' and changed.version!=convert.version



@pytest.mark.parametrize('suffix',['20260930','2026-02-30','/private/tmp/secret','2026-09-30:secret'])
def test_missing_day_message_does_not_expose_invalid_private_reason(suffix):
    from src.biz.services.wealth.data_center.errors import mapped_error
    error=mapped_error('source_day_missing:'+suffix)
    assert error.code=='DC_SOURCE_UNAVAILABLE'
    assert error.message=='所需本地公告数据尚不可读取'



def test_name_snapshot_fixed_contract_from_current_dg_paths():
    import ast
    path=Path(__file__).parents[1]/'lake_console/orchestrator/src/orchestrator/defs/paths.py'
    parsed=ast.parse(path.read_text())
    for symbol,kind in [('raw_stock_basic_path','stock_basic'),('raw_namechange_path','namechange')]:
        fn=next(n for n in parsed.body if isinstance(n,ast.FunctionDef) and n.name==symbol)
        call=fn.body[0].value
        assert [ast.literal_eval(v) for v in call.args[2:]]==['tushare',kind,'full','part-000.parquet']


@pytest.mark.parametrize('damage',[None,'index','scope'])
def test_migration_catalog_schema_check_preserves_read_only_source(tmp_path,damage):
    import hashlib
    import sqlite3
    from src.foundation.clients.announcement_archive.core import Blocked
    from src.foundation.dao.announcement_archive.catalog import SCHEMA,LegacyCatalogSchema
    path=tmp_path/'legacy.sqlite'
    with sqlite3.connect(path) as conn:
        for sql in SCHEMA:conn.execute(sql)
        conn.execute("INSERT INTO catalog_meta(singleton,schema_version,source_scope) VALUES(1,2,'scope')")
        if damage=='index':conn.execute('DROP INDEX query_pending')
        if damage=='scope':conn.execute("UPDATE catalog_meta SET source_scope='other'")
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as conn:
        conn.execute('PRAGMA query_only=ON')
        if damage:
            with pytest.raises(Blocked,match='catalog_schema_invalid'):LegacyCatalogSchema('scope').validate(conn)
        else:LegacyCatalogSchema('scope').validate(conn)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
