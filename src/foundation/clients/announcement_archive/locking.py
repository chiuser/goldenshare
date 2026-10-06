"""Local execution lock survives loss/replacement of the external mount."""
from __future__ import annotations
import fcntl
import os
import stat
from pathlib import Path
from .core import Blocked


class ExecutionLock:
    def __init__(self, path: Path):
        self.path, self.fd = Path(path), -1

    def open(self):
        from .volume import no_symlinks
        no_symlinks(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise Blocked('unsafe_execution_lock')
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Blocked('archive_already_running') from None
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
