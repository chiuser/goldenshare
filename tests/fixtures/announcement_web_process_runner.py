"""DC3 subprocess crash fixture: only caller-supplied temporary files and injected HTTP."""
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
import httpx
from src.foundation.clients.announcement_archive import volume as module
from src.foundation.clients.announcement_archive.binding import ArchiveBinding
from src.foundation.clients.announcement_archive.core import DownloadPolicy
from src.foundation.clients.announcement_archive.volume import Volume,SourceVolume
from src.foundation.clients.announcement_archive.source import Source
from src.foundation.clients.announcement_archive.files import Files
from src.foundation.dao.announcement_archive.query_controls import QueryControls
from src.foundation.dao.announcement_archive.pg_database import ArchiveDatabase
from src.foundation.config.announcement_archive import ArchiveDatabasePolicy
from src.foundation.dao.announcement_archive.ledger import Ledger
from src.ops.runtime.announcement_archive.supervisor import ArchiveSupervisor

PDF=b'%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n'


def main():
    config=json.loads(Path(sys.argv[1]).read_text());mode=sys.argv[2]
    mount=Path(config['mount']);output=mount/'announcements'
    if not mount.is_relative_to(Path('/private/var')) and not mount.is_relative_to(Path('/private/tmp')):
        raise ValueError('temporary fixture required')
    module.sys.platform='darwin';module.os.path.ismount=lambda p:Path(p)==mount
    info=dict(MountPoint=str(mount),VolumeUUID='test-external-volume',DeviceIdentifier='disk7s1',WritableVolume=True,Internal=False,VirtualOrPhysical='Physical')
    policy=replace(DownloadPolicy(),reserve_bytes=0,max_file_size=1024,batch_size=500,backoff_seconds=0)
    binding=ArchiveBinding(Path(config['binding']),output)
    binding.execution_lock_path=lambda value=None:Path(config['lock'])
    Volume.execution_lock_path=lambda self:Path(config['lock'])
    def factory(options,control,*,source_required=True):
        volume=Volume(output,control.policy,lambda _:info).open()
        source=Source(options,control.policy,control,SourceVolume(Path(config['raw']),control.policy,lambda _:info)).open() if source_required else None
        ledger=Ledger(database,volume.volume_uuid,volume.relative_root)
        return volume,ledger,source
    calls=Path(config['calls'])
    class ExitStream(httpx.SyncByteStream):
        def __iter__(self):yield b'%PDF-1.7\n';os._exit(73)
    def handle(request):
        with calls.open('a') as stream:stream.write(str(request.url)+'\n');stream.flush();os.fsync(stream.fileno())
        if mode=='downloading' and len(calls.read_text().splitlines())==2:return httpx.Response(200,stream=ExitStream())
        return httpx.Response(200,content=PDF)
    if mode=='prepared':Files.promote=lambda *_:os._exit(73)
    if mode=='renamed':
        original=Ledger.state
        def state(self,key,value,error=None):
            if value=='succeeded':os._exit(73)
            return original(self,key,value,error)
        Ledger.state=state
    if mode=='preparing':
        original=Ledger.ingest
        def ingest(self,*args,**kwargs):original(self,*args,**kwargs);os._exit(73)
        Ledger.ingest=ingest
    if mode=='receipt':
        original=Ledger.begin_run
        def begin(self,*args,**kwargs):original(self,*args,**kwargs);os._exit(73)
        Ledger.begin_run=begin
    database=ArchiveDatabase(config['pg_url'],replace(ArchiveDatabasePolicy(),**config['pg_policy']))
    controls=QueryControls(database,config['archive_id'],config['scope'])
    supervisor=ArchiveSupervisor(binding,factory,lambda:controls,database,policy=policy,client_factory=lambda:httpx.Client(transport=httpx.MockTransport(handle)))
    if mode=='recover':supervisor.recover();return 0
    if mode=='lock':
        try:Volume(output,policy,lambda _:info).open()
        except Exception as error:print(str(error));return 0
        raise AssertionError('lock unexpectedly acquired')
    kind='continue' if mode=='continue' else 'create'
    payload={'runId':config['run']} if kind=='continue' else {'previewId':config['preview']}
    run=supervisor.submit(kind,payload,config['key'],'process-fixture')
    if supervisor.thread:supervisor.thread.join(timeout=25)
    print(json.dumps(dict(runId=run,error=supervisor.last_error)))
    supervisor.close();return 0

if __name__=='__main__':raise SystemExit(main())
