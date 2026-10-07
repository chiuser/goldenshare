"""Last verified archive identity, so local history remains readable without the disk."""
import json
import os
import stat
from pathlib import Path
from .core import Blocked, DownloadOptions, identity
from .volume import no_symlinks


class ArchiveBinding:
    def __init__(self, path=None, output=DownloadOptions.output_root):
        self.path = Path(path or Path.home()/'Library/Application Support/Goldenshare/announcement-download/web-archive.json')
        self.output = Path(output).absolute()

    def read(self):
        no_symlinks(self.path)
        if not self.path.exists():
            raise Blocked('archive_binding_missing')
        try:
            fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'r') as stream:
                facts=os.fstat(stream.fileno())
                if not stat.S_ISREG(facts.st_mode) or facts.st_nlink!=1 or facts.st_size>4096:raise ValueError
                value=json.loads(stream.read(4097))
            if (set(value) != {'version','volumeUuid','rootRelativePath','archiveLocation'}
                    or value['version'] != 1 or value['archiveLocation'] != str(self.output)
                    or not isinstance(value['volumeUuid'],str) or not value['volumeUuid']
                    or value['rootRelativePath'] != 'announcements'):
                raise ValueError
        except (OSError,ValueError,TypeError,KeyError):
            raise Blocked('archive_binding_invalid') from None
        return value

    def remember(self, volume):
        if volume.output != self.output or volume.relative_root != 'announcements':
            raise Blocked('archive_identity_mismatch')
        no_symlinks(self.path)
        value = dict(version=1,volumeUuid=volume.volume_uuid,rootRelativePath=volume.relative_root,archiveLocation=str(self.output))
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        temp = self.path.with_name(self.path.name+'.'+os.urandom(8).hex()+'.tmp')
        try:
            fd = os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as stream:
                json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,self.path)
            directory=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if temp.exists(): temp.unlink()

    def execution_lock_path(self, value=None):
        value = value or self.read()
        return self.path.parent / identity([value['volumeUuid'],value['rootRelativePath']]) / 'execution.lock'
