"""PG success facts plus safe file-size observation; never updates the ledger."""
import os
import stat
from pathlib import PurePosixPath
from .core import Blocked


class QueryPresence:
    def __init__(self,volume,controls,prefix):
        self.volume,self.controls,self.prefix=volume,controls,prefix
        self.identity=controls.archive_id;self.stat_count=0

    def assert_valid(self,full=False):self.volume.assert_valid(full=full)

    def check_rows(self,rows):
        if len(rows)>500:raise ValueError('presence_batch_limit')
        self.assert_valid();present=set()
        for row in rows:
            relative=row['relative_path']
            if relative is None:raise Blocked('archive_relative_path_missing')
            path=PurePosixPath(relative)
            if path.is_absolute() or '..' in path.parts or not path.parts or '\\' in relative:raise Blocked('unsafe_relative_path')
            try:
                with self.volume.directory('/'.join(p for p in (self.prefix,str(path.parent)) if p)) as fd:
                    self.stat_count+=1;info=os.stat(path.name,dir_fd=fd,follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_dev!=self.volume.device:raise Blocked('unsafe_archive_file')
                    if row['size'] is None:raise Blocked('archive_file_size_unknown')
                    if info.st_size==row['size']:present.add(row['artifact_key'])
            except FileNotFoundError:continue
            except OSError:raise Blocked('archive_presence_unavailable') from None
        self.assert_valid();return present

    def check(self,keys):
        self.assert_valid()
        return self.check_rows(self.controls.artifact_rows(keys))

    def current_run(self):
        rows=self.controls.rows('archive_execution',limit=1)
        return rows[0]['active_run_id'] if rows else None

    def close(self):self.volume.close()
