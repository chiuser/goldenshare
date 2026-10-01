from __future__ import annotations

import fcntl
import os
import plistlib
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from .core import Blocked, DownloadPolicy, identity


def disk_info(target: str, timeout: float = DownloadPolicy.volume_timeout) -> dict:
    try:
        result = subprocess.run(['/usr/sbin/diskutil', 'info', '-plist', target],
                                capture_output=True, timeout=timeout, check=True)
        parsed = plistlib.loads(result.stdout)
        if not isinstance(parsed, dict):
            raise ValueError
        return parsed
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, ValueError):
        raise Blocked('volume_information_unavailable') from None


def no_symlinks(path: Path):
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink():
            raise Blocked('symlink_path_forbidden')


def external_volume(info: dict, inspector=disk_info) -> str:
    if not info.get('MountPoint') or not info.get('VolumeUUID'):
        raise Blocked('volume_not_mounted')
    if info.get('WritableVolume', info.get('Writable')) is not True:
        raise Blocked('volume_read_only')
    stores = info.get('APFSPhysicalStores')
    if info.get('FilesystemType') == 'apfs' and not stores:
        raise Blocked('physical_store_unknown')
    try:
        physical = [inspector(s['APFSPhysicalStore']) for s in stores] if stores else [info]
    except (KeyError, TypeError):
        raise Blocked('physical_store_unknown') from None
    for item in physical:
        if item.get('Internal') is not False or item.get('OSInternalMedia') is True:
            raise Blocked('external_physical_disk_required')
        if item.get('VirtualOrPhysical') == 'Virtual' or item.get('DiskImage') is True:
            raise Blocked('disk_image_forbidden')
        if item.get('SystemImage') is True or item.get('BusProtocol') == 'Disk Image':
            raise Blocked('disk_image_forbidden')
        if not item.get('DeviceTreePath') and item.get('VirtualOrPhysical') != 'Physical':
            raise Blocked('physical_store_unknown')
        # APFS synthetic volumes are permitted only after tracing physical stores.
        if not stores and item.get('Virtual') is True:
            raise Blocked('physical_store_unknown')
    return str(info['VolumeUUID'])


class Volume:
    """All external writes are anchored to directory descriptors, never a re-opened mount path."""

    def __init__(self, output: Path, policy: DownloadPolicy, inspector=None):
        self.output = Path(os.path.abspath(output))
        self.policy = policy
        self.inspector = inspector or (lambda target: disk_info(target, policy.volume_timeout))
        self.root_fd = self.mount_fd = self.lock_fd = -1

    def open(self):
        if sys.platform != 'darwin':
            raise Blocked('macOS_required')
        no_symlinks(self.output)
        mount = self.output
        while not os.path.ismount(mount) and mount != mount.parent:
            mount = mount.parent
        if mount == Path('/'):
            raise Blocked('external_mount_required')
        info = self.inspector(str(mount))
        self.volume_uuid = external_volume(info, self.inspector)
        self.mount = mount
        if Path(info['MountPoint']) != mount:
            raise Blocked('mount_identity_mismatch')
        self.relative_root = self.output.relative_to(mount).as_posix()
        forbidden = ('data_lake', 'data_lake_staging', 'goldenshare-tushare-lake')
        if self.relative_root.split('/')[0].casefold() in forbidden:
            raise Blocked('lake_path_forbidden')
        self.device_id = info.get('DeviceIdentifier')
        self.mount_fd = os.open(mount, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.device = os.fstat(self.mount_fd).st_dev
        self.assert_valid(full=True)
        self.check_space(policy_file=True, fd=self.mount_fd)
        # Probe only after the mounted physical volume has been verified.
        probe = f'.announcement-probe-{uuid.uuid4().hex}'
        fd = -1
        try:
            fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=self.mount_fd)
            os.write(fd, b'announcement-download probe\n')
            os.fsync(fd)
            os.fsync(self.mount_fd)
        finally:
            if fd >= 0:
                os.close(fd)
                os.unlink(probe, dir_fd=self.mount_fd)
                os.fsync(self.mount_fd)
        self.root_fd = self._walk(self.mount_fd, self.relative_root, create=True)
        with self.directory('.state', create=True) as state:
            self.lock_fd = os.open('archive.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                                   0o600, dir_fd=state)
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Blocked('archive_already_running') from None
        return self

    def assert_valid(self, full=False):
        no_symlinks(self.output)
        if (not os.path.ismount(self.mount) or os.stat(self.mount).st_dev != self.device
                or os.fstat(self.mount_fd).st_dev != self.device):
            raise Blocked('volume_disconnected_or_changed')
        if full:
            info = self.inspector(str(self.mount))
            if (info.get('VolumeUUID') != self.volume_uuid or info.get('DeviceIdentifier') != self.device_id
                    or info.get('MountPoint') != str(self.mount)
                    or info.get('WritableVolume', info.get('Writable')) is not True):
                raise Blocked('volume_disconnected_or_changed')
        if self.root_fd >= 0 and os.fstat(self.root_fd).st_dev != self.device:
            raise Blocked('archive_device_changed')

    def check_space(self, policy_file=False, fd=None):
        stats = os.fstatvfs(self.root_fd if fd is None else fd)
        required = self.policy.reserve_bytes + (self.policy.max_file_size if policy_file else 0)
        if stats.f_bavail * stats.f_frsize < required:
            raise Blocked('insufficient_disk_space')

    def _walk(self, base: int, relative: str, create=False):
        path = PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts:
            raise Blocked('unsafe_relative_path')
        current = os.dup(base)
        try:
            for part in path.parts:
                if create:
                    self.assert_valid()
                    try:
                        os.mkdir(part, dir_fd=current)
                        os.fsync(current)
                    except FileExistsError:
                        pass
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=current)
                if os.fstat(next_fd).st_dev != self.device:
                    os.close(next_fd)
                    raise Blocked('cross_device_directory')
                os.close(current)
                current = next_fd
            return current
        except BaseException:
            os.close(current)
            raise

    @contextmanager
    def directory(self, relative: str, create=False):
        self.assert_valid()
        fd = self._walk(self.root_fd, relative, create)
        try:
            yield fd
        finally:
            os.close(fd)

    def occupied(self, relative: str) -> bool:
        import unicodedata
        path = PurePosixPath(relative)
        try:
            with self.directory(str(path.parent)) as fd:
                folded = unicodedata.normalize('NFC', path.name).casefold()
                return any(unicodedata.normalize('NFC', n).casefold() == folded for n in os.listdir(fd))
        except FileNotFoundError:
            return False

    def ledger_path(self) -> Path:
        archive_id = identity([self.volume_uuid, self.relative_root])
        return Path.home() / 'Library/Application Support/Goldenshare/announcement-download' / archive_id / 'downloads.sqlite'

    def close(self):
        for name in ('lock_fd', 'root_fd', 'mount_fd'):
            fd = getattr(self, name)
            if fd >= 0:
                os.close(fd)
                setattr(self, name, -1)
