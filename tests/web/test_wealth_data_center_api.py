"""Real registered routes and real Biz/DAO, with only temporary storage/auth fixtures."""
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from test_announcement_catalog import query_archive,archive,request,row,pg,pg_cluster
from test_announcement_download_dg import write_day,raw_root
from src.app.auth.dependencies import get_current_user
from src.app.exceptions import WebAppError,install_exception_handlers
from src.app.runtime.announcement_archive_lifespan import include_data_center,install_data_center
from src.ops.runtime.announcement_archive.source_runtime import AnnouncementSourceRuntime
from src.foundation.config.settings import Settings,get_settings
from src.foundation.config.announcement_archive import announcements_enabled

PREFIX='/api/v1/wealth/data-center'


@pytest.fixture
def dc_client(query_archive,monkeypatch):
    service,archive,_=query_archive
    settings=Settings(WEALTH_LOCAL_ANNOUNCEMENTS_ENABLED=True,APP_ENV='local')
    monkeypatch.setattr('src.biz.api.wealth.data_center.home.get_settings',lambda:settings)
    monkeypatch.setattr('src.biz.api.wealth.data_center.announcements.get_settings',lambda:settings)
    monkeypatch.setattr('src.biz.api.wealth.data_center.downloads.get_settings',lambda:settings)
    write_day(raw_root(archive),'2026-09-30',[row()])
    app=FastAPI();install_exception_handlers(app);install_data_center(app)
    from fastapi import APIRouter
    router=APIRouter(prefix='/api/v1');include_data_center(router);app.include_router(router)
    # Existing login dependency is replaced; business query/service/DAO are real.
    app.dependency_overrides[get_current_user]=lambda:object()
    runtime=AnnouncementSourceRuntime(lambda wake:(service,service.fixture_preparation),service.policy)
    service.wake=runtime.wake.set
    app.state.announcement_source=runtime.start()
    with TestClient(app) as client:
        yield client,service,settings,app
    runtime.close()


def poll(client,query_id):
    for _ in range(100):
        response=client.get(PREFIX+'/announcements/queries/'+query_id)
        if response.status_code!=202:return response
        time.sleep(.01)
    raise AssertionError('query never finished')


def test_home_registered_routes_and_real_query(dc_client):
    client,service,settings,_=dc_client
    modules=client.get(PREFIX+'/modules')
    assert modules.status_code==200 and len(modules.json()['modules'])==1
    context=client.get(PREFIX+'/announcements/context').json()
    assert context['sourceUpdateSucceededAt'] is None and context['downloadDefaults']['startDate'] is None
    created=client.post(PREFIX+'/announcements/queries',json=request().model_dump(mode='json'))
    assert created.status_code==202 and created.json()['total'] is None
    response=poll(client,created.json()['queryId'])
    assert response.status_code==200 and response.json()['total']==1
    row=response.json()['items'][0]
    assert set(row)=={'recordKey','annDate','tsCode','companyName','companyNameSource','title','sourceUrl','downloadStatus','statusCheckedAt'}
    assert row['downloadStatus']=='undownloaded' and row['sourceUrl'].startswith('https://')
    assert 'relative_path' not in response.text and 'local-state' not in response.text
    candidates=client.get(PREFIX+'/announcements/companies',params=dict(keyword='SFZA',startDate='2026-09-30',endDate='2026-09-30'))
    assert candidates.status_code==200 and candidates.json()['items'][0]['matchedAlias']=='深发展A'
    assert client.get(PREFIX+'/announcements/pdf/example').status_code==404
    assert client.post(PREFIX+'/announcements/runs',json={}).status_code in {422,503} # Download storage not supplied by this query-only fixture.


def test_missing_latest_date_does_not_block_master_candidates_or_historical_queries(dc_client,query_archive):
    client,service,_,_=dc_client
    write_day(raw_root(query_archive[1]),'2026-09-30',[row(code='000001.SZ')])
    missing_body={**request().model_dump(mode='json'),'endDate':'2026-10-08'}
    failed=client.post(PREFIX+'/announcements/queries',json=missing_body)
    adjusted=poll(client,failed.json()['queryId']).json()
    assert adjusted['pageState']['status']=='ready'
    assert adjusted['effectiveEndDate']=='2026-09-30' and adjusted['conditions']['endDate']=='2026-10-08'
    candidates=client.get(PREFIX+'/announcements/companies',params=dict(keyword='payh',startDate='2026-09-30',endDate='2026-10-08'))
    assert candidates.status_code==200
    assert candidates.json()['items'][0]['tsCode']=='000001.SZ'
    assert candidates.json()['pageState'] is None
    body={**request().model_dump(mode='json'),'tsCode':'000001.SZ'}
    historic=client.post(PREFIX+'/announcements/queries',json=body)
    result=poll(client,historic.json()['queryId']).json()
    assert result['pageState']['status']=='ready' and result['total']==1
    assert result['items'][0]['tsCode']=='000001.SZ'
    assert client.get(PREFIX+'/announcements/queries/'+failed.json()['queryId']).json()['pageState']['status']=='ready'


def test_announcement_only_company_still_prepares_the_requested_range(dc_client,query_archive):
    client,service,_,_=dc_client
    write_day(raw_root(query_archive[1]),'2026-09-30',[row(code='155162.SH',title='样本债券公告')])
    params=dict(keyword='155162',startDate='2026-09-30',endDate='2026-09-30')
    first=client.get(PREFIX+'/announcements/companies',params=params)
    assert first.status_code==202 and first.json()['items']==[]
    assert poll(client,first.json()['queryId']).json()['pageState']['status']=='ready'
    result=client.get(PREFIX+'/announcements/companies',params=params).json()
    assert result['items'][0]['tsCode']=='155162.SH' and result['items'][0]['nameSource']=='announcement'
    missing=client.get(PREFIX+'/announcements/companies',params={**params,'endDate':'2026-10-08'})
    assert missing.status_code==202
    assert poll(client,missing.json()['queryId']).json()['pageState']['status']=='ready'
    result=client.get(PREFIX+'/announcements/companies',params={**params,'endDate':'2026-10-08'}).json()
    assert result['items'][0]['tsCode']=='155162.SH' and result['queryId'] is None
    with service.controls.transaction(read_only=True) as conn:
        from sqlalchemy import text
        assert conn.scalar(text('SELECT count(*) FROM announcement_archive.query_snapshots'))==2


@pytest.mark.parametrize('missing,start,end',[
    ('2026-10-01','2026-09-30','2026-10-02'),
    ('2026-09-29','2026-09-29','2026-09-30')])
def test_failed_query_is_terminal_with_actual_missing_date_and_manual_requery(dc_client,query_archive,missing,start,end):
    client,service,_,_=dc_client
    _,archive,_=query_archive
    if end not in {missing,'2026-09-30'}:
        write_day(raw_root(archive),end,[])
    body={**request().model_dump(mode='json'),'startDate':start,'endDate':end}
    created=client.post(PREFIX+'/announcements/queries',json=body)
    assert created.status_code==202
    query_id=created.json()['queryId']
    failed=poll(client,query_id)
    assert failed.status_code==200
    result=failed.json()
    assert result['pageState']['status']=='error' and result['pageState']['code']=='DC_SOURCE_UNAVAILABLE'
    assert missing in result['pageState']['message']
    assert result['total'] is None and result['items']==[] and result['preparation'] is None
    assert not result['downloadStatusAvailable']
    assert str(raw_root(archive)) not in failed.text
    write_day(raw_root(archive),missing,[])
    assert client.get(PREFIX+'/announcements/queries/'+query_id).json()==result
    fresh=client.post(PREFIX+'/announcements/queries',json=body)
    assert fresh.json()['queryId']!=query_id
    ready=poll(client,fresh.json()['queryId'])
    assert ready.status_code==200 and ready.json()['pageState']['status']=='ready'
    assert ready.json()['total']==1


def test_login_first_then_capability_and_prod(dc_client):
    client,_,settings,app=dc_client
    def unauthorized():raise WebAppError(status_code=401,code='unauthorized',message='请先登录')
    app.dependency_overrides[get_current_user]=unauthorized
    assert client.get(PREFIX+'/modules').status_code==401
    assert client.post(PREFIX+'/announcements/queries',json={}).status_code==401
    settings.app_env='prod'
    assert client.get(PREFIX+'/announcements/context').status_code==401
    app.dependency_overrides[get_current_user]=lambda:object()
    assert client.get(PREFIX+'/modules').json()=={'modules':[]}
    unavailable=client.get(PREFIX+'/announcements/context')
    assert unavailable.status_code==404 and unavailable.json()['code']=='DC_MODULE_UNAVAILABLE'
    settings.app_env='local';settings.wealth_local_announcements_enabled=False
    assert client.get(PREFIX+'/modules').json()=={'modules':[]}
    assert not announcements_enabled(Settings(APP_ENV='prod',WEALTH_LOCAL_ANNOUNCEMENTS_ENABLED=True))


@pytest.mark.parametrize('extra',[{'url':'https://x'},{'outputRoot':'/tmp'},{'intervalSeconds':0},{'companyName':'平安'},{'effectiveEndDate':'2026-09-30'}])
def test_query_extra_forbidden(dc_client,extra):
    client,_,_,_=dc_client
    assert client.post(PREFIX+'/announcements/queries',json={**request().model_dump(mode='json'),**extra}).status_code==422


def test_invalid_dates_page_keyword_and_unknown_object(dc_client):
    client,_,_,_=dc_client
    for body in [{'startDate':'20260930'},{'startDate':'2026-10-01','endDate':'2026-09-30'},{'titleKeyword':'a'*201},{'downloadStatus':'unknown'}]:
        assert client.post(PREFIX+'/announcements/queries',json=body).status_code==422
    assert client.get(PREFIX+'/announcements/queries/missing').status_code==404
    assert client.get(PREFIX+'/announcements/queries/missing?page=0').status_code==422
    assert client.get(PREFIX+'/announcements/companies',params={'keyword':'a'*65}).status_code==422


def test_unplug_keeps_card_unknown_download_status(dc_client,monkeypatch):
    client,service,_,_=dc_client
    created=client.post(PREFIX+'/announcements/queries',json=request().model_dump(mode='json'))
    response=poll(client,created.json()['queryId']);assert response.status_code==200
    from src.foundation.clients.announcement_archive.core import Blocked
    monkeypatch.setattr(service.presence,'check',lambda keys:(_ for _ in ()).throw(Blocked('archive_presence_unavailable')))
    assert len(client.get(PREFIX+'/modules').json()['modules'])==1
    response=client.get(PREFIX+'/announcements/queries/'+created.json()['queryId'])
    assert response.status_code==200 and response.json()['items'][0]['downloadStatus'] is None


def test_actual_app_registers_data_center_and_blocks_prod_direct_page(dc_client,monkeypatch):
    import importlib
    actual=importlib.import_module('src.app.web.app')
    from fastapi.testclient import TestClient
    _,_,settings,_=dc_client
    settings.app_env='prod'
    monkeypatch.setattr(actual,'get_settings',lambda:settings)
    previous=actual.app.dependency_overrides.get(get_current_user)
    actual.app.dependency_overrides[get_current_user]=lambda:object()
    try:
        # No lifespan started: neither formal catalog nor database is opened here.
        client=TestClient(actual.app)
        assert client.get(PREFIX+'/modules').json()=={'modules':[]}
        assert client.get(PREFIX+'/announcements/context').status_code==404
        assert client.get('/wealth/data-center/announcements').status_code==404
        assert client.get('/wealth/data-center/announcements/any').status_code==404
    finally:
        if previous is None:actual.app.dependency_overrides.pop(get_current_user,None)
        else:actual.app.dependency_overrides[get_current_user]=previous


@pytest.mark.parametrize('dates',[{'startDate':'2026-10-01','endDate':'2026-09-30'},
                                  {'startDate':'2026-02-30'},{'startDate':'20260930'}])
def test_company_dates_reject_cleanly(dc_client,dates):
    client,_,_,_=dc_client
    response=client.get(PREFIX+'/announcements/companies',params={'keyword':'PAYH',**dates})
    assert response.status_code==422 and response.json()['code']=='DC_REQUEST_INVALID'


def test_optional_dependencies_do_not_load_in_prod_subprocess(tmp_path):
    import subprocess,sys,os
    result=subprocess.run([sys.executable,'-B','-c',
      "import sys; from src.app.api.v1.router import router; assert 'pypinyin' not in sys.modules; assert 'duckdb' not in sys.modules; print('prod imports safe')"],
      env={**os.environ,'APP_ENV':'prod','WEALTH_LOCAL_ANNOUNCEMENTS_ENABLED':'false'},capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('path',[ '/announcements/context?extra=1',
                                '/announcements/companies?keyword=PAYH&limit=100',
                                '/announcements/companies?keyword=PAYH&keyword=SFZA',
                                '/announcements/queries/missing?page=1&sourceUrl=x'])
def test_get_extra_or_duplicate_parameters_forbidden(dc_client,path):
    response=dc_client[0].get(PREFIX+path)
    assert response.status_code==422 and response.json()['code']=='DC_REQUEST_INVALID'
