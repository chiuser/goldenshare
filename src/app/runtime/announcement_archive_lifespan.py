"""Composition only: local PG + one Ops source runtime; no SQLite fallback."""
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import date
from fastapi import Depends,Request
from fastapi.responses import JSONResponse
from src.app.auth.dependencies import get_current_user
from src.foundation.clients.announcement_archive.core import Blocked,Control,DownloadPolicy,DownloadOptions,identity
from src.foundation.clients.announcement_archive.volume import SourceVolume
from src.foundation.config.announcement_archive import DataCenterPolicy,announcements_enabled
from src.foundation.config.settings import get_settings
from src.biz.services.wealth.data_center.errors import DataCenterError


def build_source_resources(wake):
    from src.foundation.dao.announcement_archive.pg_database import configured_archive_database
    from src.foundation.dao.announcement_archive.query_controls import QueryControls
    from src.foundation.clients.announcement_archive.direct_source import DirectSource
    from src.foundation.clients.announcement_archive.query_presence import QueryPresence
    from src.foundation.clients.announcement_archive.source import RAW_ROOT
    from src.foundation.clients.announcement_archive.names import NAME_ROOT
    from src.biz.services.wealth.data_center.query_service import AnnouncementQueryService
    from src.ops.runtime.announcement_archive.source_runtime import SourcePreparation
    policy=DataCenterPolicy();control=Control(DownloadPolicy(),emit=lambda _:None)
    database=configured_archive_database(get_settings());volumes=[];source=None
    try:
        for path in (RAW_ROOT,NAME_ROOT,Path('/Volumes/datasource')):
            volume=SourceVolume(path,control.policy);volumes.append(volume);volume.open()
        root=DownloadOptions(date.today(),date.today()).output_root.relative_to(volumes[2].mount).as_posix()
        archive_id=identity([volumes[2].volume_uuid,root])
        source=DirectSource(volumes[0],volumes[1],control,policy)
        controls=QueryControls(database,archive_id,source.scope,policy)
        presence=QueryPresence(volumes[2],controls,root)
        service=AnnouncementQueryService(controls,source,presence,policy,wake)
        return service,SourcePreparation(source,controls,presence,policy)
    except BaseException:
        if source:source.close()
        for volume in volumes:volume.close()
        if database:database.close()
        raise


@asynccontextmanager
async def announcement_archive_lifespan(app):
    runtime=None
    if announcements_enabled(get_settings()):
        from src.ops.runtime.announcement_archive.source_runtime import AnnouncementSourceRuntime
        from src.biz.services.wealth.data_center.download_service import AnnouncementDownloadService
        runtime=AnnouncementSourceRuntime(build_source_resources,DataCenterPolicy()).start()
        app.state.announcement_source=runtime
        # Q2 only reads/prepares. Q3 supplies the PG execution store and supervisor.
        def controls():return runtime.service().controls
        app.state.announcement_download=AnnouncementDownloadService(None,None,controls,lambda:runtime.service().presence.identity,runtime.wake.set)
    try:yield
    finally:
        if runtime:
            runtime.close();del app.state.announcement_source;del app.state.announcement_download


def install_data_center(app):
    @app.exception_handler(DataCenterError)
    async def handle(_request,error):
        return JSONResponse(dict(code=error.code,message=error.message,request_id=getattr(_request.state,'request_id',None)),status_code=error.status)


def include_data_center(router):
    from src.biz.api.wealth.data_center import home,announcements,downloads
    router.include_router(home.router,dependencies=[Depends(get_current_user)])
    router.include_router(announcements.router,dependencies=[Depends(get_current_user)])
    def actor(request: Request,user=Depends(get_current_user)):
        request.state.announcement_actor=str(user.id) if hasattr(user,'id') else None
    router.include_router(downloads.router,dependencies=[Depends(actor)])
