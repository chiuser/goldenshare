"""App composition: one serial, lifecycle-owned local query preparation thread."""
from contextlib import asynccontextmanager
import threading
import time
from datetime import date
from pathlib import Path

from fastapi import Depends
from fastapi.responses import JSONResponse

from src.app.auth.dependencies import get_current_user
from src.foundation.clients.announcement_archive.core import Blocked,Control,DownloadOptions,DownloadPolicy
from src.foundation.clients.announcement_archive.source import Source
from src.foundation.clients.announcement_archive.volume import SourceVolume
from src.foundation.clients.announcement_archive.locking import ExecutionLock
from src.foundation.config.announcement_archive import DataCenterPolicy,announcements_enabled
from src.foundation.config.settings import get_settings
from src.foundation.dao.announcement_archive.catalog import Catalog,catalog_path
from src.biz.services.wealth.data_center.errors import DataCenterError,mapped_error
from src.biz.services.wealth.data_center.query_service import AnnouncementQueryService
from src.ops.runtime.announcement_archive.catalog_builder import CatalogBuilder


def build_query_service(wake,control):
    # Local optional imports are behind the deployment capability; Prod does not load pypinyin/DuckDB.
    from src.foundation.clients.announcement_archive.names import NAME_ROOT,NameInitials
    from src.foundation.clients.announcement_archive.presence import ArchivePresence
    policy=control.policy
    options=DownloadOptions(date.today(),date.today())
    sources=[];volume=None
    try:
        source=Source(options,policy,control).open();sources.append(source)
        names=Source(options,policy,control,SourceVolume(NAME_ROOT,policy)).open();sources.append(names)
        volume=SourceVolume(Path('/Volumes/datasource'),policy).open()
        root=options.output_root.relative_to(volume.mount).as_posix()
        # Same UUID/root algorithm as the CLI; no writer lock, migration or probe.
        from src.foundation.clients.announcement_archive.core import identity
        ledger_path=Path.home()/'Library/Application Support/Goldenshare/announcement-download'/identity([volume.volume_uuid,root])/'downloads.sqlite'
        presence=ArchivePresence(volume,ledger_path,root,root)
        catalog=Catalog(catalog_path(source.scope),source.scope)
        lock=ExecutionLock(catalog.path.parent/'catalog-writer.lock').open()
        try:
            with catalog.connection(write=True,initialize=True):
                pass
        finally:
            lock.close()
        builder=CatalogBuilder(catalog,source,names,NameInitials())
        return AnnouncementQueryService(catalog,builder,presence,wake=wake)
    except BaseException:
        for value in sources:
            value.close()
        if volume:
            volume.close()
        raise


class AnnouncementCatalogRuntime:
    def __init__(self,factory=build_query_service,policy=DataCenterPolicy()):
        self.factory,self.policy=factory,policy
        self.wake,self.stop=threading.Event(),threading.Event()
        self.control=Control(DownloadPolicy(),emit=lambda _:None)
        self._service=None
        self.error='source_unavailable'
        self.last_checked=0
        self.thread=threading.Thread(target=self._run,name='announcement-catalog',daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _run(self):
        while not self.stop.is_set():
            self.wake.clear()
            try:
                if self._service is None:
                    self._service=self.factory(self.wake.set,self.control)
                if time.monotonic()-self.last_checked>=self.policy.catalog_check_seconds:
                    try:
                        self._service.validate_sources()
                    except (Blocked,OSError):
                        previous=self._service
                        self._service=None
                        previous.builder.close()
                        previous.presence.close()
                        raise Blocked('source_unavailable') from None
                    self.last_checked=time.monotonic()
                while not self.stop.is_set() and self._service.prepare_next():
                    pass
            except Blocked as error:
                self.error=str(error)
            except Exception:
                self.error='catalog_build_failed'
            self.wake.wait(self.policy.control_poll_seconds if self._service else self.policy.catalog_check_seconds)
        if self._service:
            self._service.builder.close()
            self._service.presence.close()

    def service(self):
        if self._service is None:
            raise mapped_error(self.error)
        return self._service

    def close(self):
        self.stop.set();self.control.stop.set();self.wake.set()
        self.thread.join(timeout=self.control.policy.source_query_timeout_seconds+self.policy.sql_seconds+1)


@asynccontextmanager
async def announcement_archive_lifespan(app):
    runtime=None
    if announcements_enabled(get_settings()):
        runtime=AnnouncementCatalogRuntime().start()
        app.state.announcement_catalog=runtime
    try:
        yield
    finally:
        if runtime:
            runtime.close()
            del app.state.announcement_catalog


def install_data_center(app):
    @app.exception_handler(DataCenterError)
    async def handle(_request,error):
        return JSONResponse(dict(code=error.code,message=error.message,request_id=getattr(_request.state,'request_id',None)),status_code=error.status)


def include_data_center(router):
    from src.biz.api.wealth.data_center import home,announcements
    router.include_router(home.router,dependencies=[Depends(get_current_user)])
    router.include_router(announcements.router,dependencies=[Depends(get_current_user)])
