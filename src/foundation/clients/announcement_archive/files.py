from __future__ import annotations

import hashlib
import os
import re
import stat
import time
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from .core import Blocked, Control, DownloadPolicy, FileFailed, Retryable, iso_date


def valid_url(url: str):
    try:
        parts = urlsplit(url)
        if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username is not None
                or parts.password is not None or any(ord(c) < 32 or ord(c) == 127 for c in url)):
            raise ValueError
        parts.port
    except ValueError:
        raise FileFailed('invalid_url') from None


def title_name(title: str, suffix: str, budget: int) -> str:
    if not isinstance(title, str):
        raise FileFailed('invalid_title')
    clean = unicodedata.normalize('NFC', title)
    clean = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', '_', clean).strip(' .')
    if not clean:
        raise FileFailed('invalid_title')
    if clean.lower().endswith('.pdf'):
        clean = clean[:-4].rstrip(' .')
    if not clean:
        raise FileFailed('invalid_title')
    tail = suffix + '.pdf'
    clean = clean.encode('utf-8')[:budget - len(tail.encode())].decode('utf-8', errors='ignore').rstrip(' .')
    if not clean:
        raise FileFailed('invalid_title')
    return clean + tail


class Files:
    def __init__(self, volume, ledger, policy: DownloadPolicy, control: Control):
        self.volume, self.ledger, self.policy, self.control = volume, ledger, policy, control

    def allocate(self, task: dict) -> dict:
        self.control.check()
        try:
            iso_date(task['ann_date'])
        except ValueError:
            raise FileFailed('invalid_ann_date') from None
        if not isinstance(task['ts_code'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', task['ts_code']):
            raise FileFailed('invalid_ts_code')
        valid_url(task['url'])
        if task['relative_path']:
            return task
        directory = f"{task['ann_date']}/{task['ts_code']}"
        for length in (0, 12, 24, 64):
            suffix = '__' + task['artifact_key'][:length] if length else ''
            name = title_name(task['title'], suffix, self.policy.filename_bytes)
            relative = directory + '/' + name
            if not self.ledger.path_taken(relative) and not self.volume.occupied(relative):
                self.ledger.assign_path(task['artifact_key'], relative)
                return self.ledger.artifact(task['artifact_key'])
        raise FileFailed('filename_collision')

    @staticmethod
    def part_name(task: dict):
        # Final names have a 200-byte budget; temp name remains below NAME_MAX.
        return '.' + task['artifact_key'] + '.part'

    def fingerprint(self, fd: int, name: str):
        try:
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return None
        with os.fdopen(handle, 'rb') as stream:
            file_stat = os.fstat(stream.fileno())
            if file_stat.st_dev != self.volume.device:
                raise Blocked('archive_file_device_changed')
            if not stat.S_ISREG(file_stat.st_mode):
                raise Blocked('non_regular_archive_file')
            if os.fstat(stream.fileno()).st_nlink != 1:
                raise Blocked('multiple_hardlinks_forbidden')
            if os.fstat(stream.fileno()).st_size > self.policy.max_file_size:
                return os.fstat(stream.fileno()).st_size, ''
            digest, size = hashlib.sha256(), 0
            while chunk := stream.read(self.policy.chunk_size):
                self.control.check()
                self.volume.assert_valid()
                digest.update(chunk)
                size += len(chunk)
            return size, digest.hexdigest()

    def matches(self, task: dict, actual):
        return actual is not None and actual == (task['size'], task['sha256'])

    def recover(self, task: dict) -> str | None:
        path = PurePosixPath(task['relative_path'])
        with self.volume.directory(str(path.parent), create=True) as fd:
            actual = self.fingerprint(fd, path.name)
            if task['state'] == 'succeeded' and self.matches(task, actual):
                return 'skipped'
            if task['state'] == 'prepared':
                if self.matches(task, actual):
                    os.fsync(fd)
                    self.ledger.state(task['artifact_key'], 'succeeded')
                    return 'succeeded'
                part = self.fingerprint(fd, self.part_name(task))
                if actual is None and self.matches(task, part):
                    self.promote(fd, task)
                    return 'succeeded'
                if actual is None:
                    raise FileFailed('prepared_evidence_mismatch')
            if actual is not None:
                # Preserve corrupt/unknown existing files and allocate a fresh path.
                self.ledger.assign_path(task['artifact_key'], None)
                task['relative_path'] = None
                self.allocate(task)
            self.ledger.state(task['artifact_key'], 'pending')
        return None

    def promote(self, fd: int, task: dict):
        self.control.check()
        self.volume.assert_valid(full=True)
        name = PurePosixPath(task['relative_path']).name
        try:
            os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileFailed('final_path_occupied')
        os.replace(self.part_name(task), name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
        self.ledger.state(task['artifact_key'], 'succeeded')

    def receive(self, task: dict, response):
        self.volume.assert_valid()
        self.volume.check_space(policy_file=True)
        if 'html' in response.headers.get('content-type', '').lower():
            raise FileFailed('html_instead_of_pdf')
        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
            raise FileFailed('unexpected_content_encoding')
        try:
            length = int(response.headers['content-length']) if 'content-length' in response.headers else None
        except ValueError:
            raise FileFailed('invalid_content_length') from None
        if length is not None and (length < 0 or length > self.policy.max_file_size):
            raise FileFailed('file_too_large')
        self.ledger.state(task['artifact_key'], 'downloading')
        path = PurePosixPath(task['relative_path'])
        with self.volume.directory(str(path.parent), create=True) as fd:
            name = self.part_name(task)
            handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                             0o600, dir_fd=fd)
            size, digest, prefix, tail = 0, hashlib.sha256(), b'', b''
            deadline = time.monotonic() + self.policy.transfer_deadline
            with os.fdopen(handle, 'wb') as stream:
                file_stat = os.fstat(stream.fileno())
                if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
                    raise Blocked('unsafe_temporary_file')
                os.ftruncate(stream.fileno(), 0)
                for chunk in response.iter_bytes(self.policy.chunk_size):
                    self.control.check()
                    self.volume.assert_valid()
                    self.volume.check_space()
                    if time.monotonic() > deadline:
                        raise Retryable('transfer_deadline_exceeded')
                    size += len(chunk)
                    if size > self.policy.max_file_size:
                        raise FileFailed('file_too_large')
                    prefix = (prefix + chunk)[:1024]
                    tail = (tail + chunk)[-2048:]
                    stream.write(chunk)
                    digest.update(chunk)
                if length is not None and size != length:
                    raise Retryable('content_length_mismatch')
                if time.monotonic() > deadline:
                    raise Retryable('transfer_deadline_exceeded')
                if not re.match(rb'%PDF-\d\.\d', prefix):
                    if b'captcha' in prefix.lower() or '验证码'.encode() in prefix:
                        raise Blocked('challenge_page')
                    raise FileFailed('invalid_pdf_header')
                if not size or b'%%EOF' not in tail:
                    raise FileFailed('invalid_pdf_tail')
                self.control.check()
                os.fsync(stream.fileno())
            os.fsync(fd)
            self.ledger.prepared(task['artifact_key'], size, digest.hexdigest())
            self.promote(fd, task)

def verify_one(task, volume, policy: DownloadPolicy, control: Control):
    """Inspect the known paths without allocate(), mkdir(), or SQLite writes."""
    control.check()
    volume.assert_valid(full=True)
    if not task['relative_path']:
        return dict(artifact_key=task['artifact_key'], ledger_state=task['state'], final=dict(status='unallocated'), part=None)
    path = PurePosixPath(task['relative_path'])
    if path.is_absolute() or '..' in path.parts or path.name in ('', '.'):
        raise Blocked('unsafe_relative_path')
    files = Files(volume, None, policy, control)
    def describe(actual):
        if actual is None:
            return dict(status='missing')
        status = 'matched' if files.matches(task, actual) else ('untracked' if task['sha256'] is None else 'mismatch')
        return dict(status=status, size=actual[0], sha256=actual[1])
    final = part = None
    try:
        with volume.directory(str(path.parent)) as fd:
            final = files.fingerprint(fd, path.name)
            if task['state'] == 'prepared':
                part = files.fingerprint(fd, files.part_name(task))
    except FileNotFoundError:
        pass
    volume.assert_valid(full=True)
    return dict(artifact_key=task['artifact_key'], ledger_state=task['state'], relative_path=task['relative_path'],
                expected_size=task['size'], expected_sha256=task['sha256'], final=describe(final),
                part=describe(part) if task['state'] == 'prepared' else None)
