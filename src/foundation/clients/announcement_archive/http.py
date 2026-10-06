from __future__ import annotations

import math
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx

from .core import Blocked, Control, DownloadOptions, DownloadPolicy, FileFailed, Retryable
from .files import valid_url
from .transport import PublicHTTPTransport


def retry_seconds(value: str | None, now: float) -> float:
    if not value:
        return 0
    try:
        if value.strip().isdigit():
            seconds = float(value)
        else:
            seconds = max(0, parsedate_to_datetime(value).timestamp() - now)
        return seconds if math.isfinite(seconds) else 0
    except (ValueError, TypeError, OverflowError):
        return 0


class Limiter:
    def __init__(self, ledger, interval: float, control: Control, volume, clock=time.time):
        self.ledger, self.interval, self.control, self.volume, self.clock = ledger, interval, control, volume, clock
        saved = ledger.cooldown()
        if saved['request_in_flight']:
            ledger.defer(clock() + interval, 'request_end_unknown')

    def before(self):
        self.control.check()
        saved = self.ledger.cooldown()
        until = max(saved['next_request_not_before'], saved['last_request_finished_at'] + self.interval)
        remaining = max(0, until - self.clock())
        if remaining:
            self.control.update(wait_until=until, waiting=True)
            self.control.wait(remaining)
        self.control.check()
        self.volume.assert_valid(full=True)
        self.ledger.request_started()
        self.control.update(waiting=False, wait_until=None)

    def after(self, delay=0, reason='interval'):
        now = self.clock()
        self.ledger.request_finished(now, now + max(self.interval, delay), reason)

    def defer(self, seconds: float, reason: str):
        self.ledger.defer(self.clock() + max(seconds, self.interval), reason)


class Downloader:
    def __init__(self, ledger, files, volume, options: DownloadOptions, policy: DownloadPolicy,
                 control: Control, client=None, clock=time.time):
        self.ledger, self.files, self.options, self.policy, self.control = ledger, files, options, policy, control
        self.clock = clock
        self.last_http_status = None
        self.limiter = Limiter(ledger, options.interval_seconds, control, volume, clock)
        self.client = client or httpx.Client(timeout=httpx.Timeout(connect=policy.connect_timeout,
            read=policy.read_timeout, write=policy.write_timeout, pool=policy.pool_timeout),
            transport=PublicHTTPTransport(control), follow_redirects=False, trust_env=False)

    def _request(self, url: str, task: dict, *, probe=False) -> str | None:
        valid_url(url)
        self.limiter.before()
        delay, reason = 0, 'interval'
        try:
            with self.client.stream('GET', url, headers={'Accept-Encoding': 'identity'},
                                    follow_redirects=False) as response:
                status = response.status_code
                self.last_http_status = status
                if status == 403:
                    raise Blocked('http_403')
                if status == 408 or status == 429 or 500 <= status <= 599:
                    delay = retry_seconds(response.headers.get('retry-after'), self.clock())
                    reason = f'http_{status}'
                    # Persist server cooldown as soon as it is known, before body/close.
                    self.limiter.defer(delay, reason)
                    raise Retryable(reason, delay)
                if status in (301, 302, 303, 307, 308):
                    location = response.headers.get('location')
                    if not location:
                        raise FileFailed('redirect_missing_location')
                    return urljoin(str(response.url), location)
                if probe and 200 <= status < 300:
                    prefix=next(response.iter_bytes(1024),b'').lower()
                    self.control.check()
                    if b'captcha' in prefix or '验证码'.encode() in prefix:raise Blocked('challenge_page')
                    return None
                if status != 200:
                    raise FileFailed(f'http_{status}')
                if 'html' in response.headers.get('content-type', '').lower():
                    prefix = next(response.iter_bytes(1024), b'').lower()
                    if b'captcha' in prefix or '验证码'.encode() in prefix:
                        raise Blocked('challenge_page')
                    raise FileFailed('html_instead_of_pdf')
                self.files.receive(task, response)
                return None
        finally:
            self.limiter.after(delay, reason)

    def download(self, run: str, task: dict):
        for attempt in range(self.policy.attempts):
            self.control.check()
            self.ledger.attempt(run, task['artifact_key'])
            url, seen = task['url'], set()
            self.last_http_status = None
            try:
                for hop in range(self.policy.redirects + 1):
                    if url in seen:
                        raise FileFailed('redirect_loop')
                    seen.add(url)
                    next_url = self._request(url, task)
                    if next_url is None:
                        self.ledger.finish_attempt(run, task['artifact_key'], 'succeeded', http_status=self.last_http_status, received=self.ledger.artifact(task['artifact_key'])['size'] or 0)
                        return
                    if hop == self.policy.redirects:
                        raise FileFailed('redirect_limit')
                    if urlsplit(url).scheme == 'https' and urlsplit(next_url).scheme != 'https':
                        raise FileFailed('https_downgrade_forbidden')
                    valid_url(next_url)
                    url = next_url
            except Retryable as exc:
                error = exc
            except (FileFailed, Blocked) as exc:
                self.ledger.finish_attempt(run, task['artifact_key'], 'failed', str(exc), self.last_http_status)
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                error = Retryable('network_or_timeout')
            except httpx.HTTPError:
                raise FileFailed('invalid_http_response') from None
            self.ledger.finish_attempt(run, task['artifact_key'], 'retryable', str(error), self.last_http_status)
            wait = max(self.policy.backoff_seconds * 2 ** attempt, error.retry_after)
            self.limiter.defer(wait, str(error))
            if attempt + 1 == self.policy.attempts:
                raise FileFailed(str(error)) from None

    def probe(self, task):
        """One limited session, sharing validated transport, redirects and persistent limiter."""
        url,seen=task['url'],set()
        for hop in range(self.policy.redirects+1):
            self.control.check()
            if url in seen:raise FileFailed('redirect_loop')
            seen.add(url)
            next_url=self._request(url,task,probe=True)
            if next_url is None:return
            if hop==self.policy.redirects:raise FileFailed('redirect_limit')
            if urlsplit(url).scheme=='https' and urlsplit(next_url).scheme!='https':raise FileFailed('https_downgrade_forbidden')
            valid_url(next_url);url=next_url

    def close(self):
        self.client.close()
