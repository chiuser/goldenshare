"""HTTP transport connects only to the validated DNS answers, preserving Host/TLS names."""
from __future__ import annotations

import ipaddress
import socket
import ssl
import threading
import time

import httpcore
import httpx

from .core import Blocked, FileFailed


def public_address(value):
    try:
        address = ipaddress.ip_address(value.split('%')[0])
    except ValueError:
        raise FileFailed('invalid_source_address') from None
    embedded = []
    if address.version == 6:
        embedded = [ip for ip in (address.ipv4_mapped, address.sixtofour) if ip is not None]
        if address.teredo:
            embedded.extend(address.teredo)
        if address in ipaddress.ip_network('64:ff9b::/96'):
            embedded.append(ipaddress.IPv4Address(int(address) & (2**32-1)))
    if (not address.is_global or address.is_multicast or address.is_reserved
            or any(not ip.is_global for ip in embedded)):
        raise FileFailed('unsafe_source_address')
    return str(address)


class PublicNetworkBackend(httpcore.SyncBackend):
    def __init__(self, control, resolver=None, connector=None):
        self.control = control
        self.resolver = resolver or socket.getaddrinfo
        self.connector = connector or super().connect_tcp

    def resolve(self, host, port, timeout):
        if host.rstrip('.').lower() == 'localhost' or '%' in host:
            raise FileFailed('unsafe_source_address')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return [public_address(host)]
        finished, result = threading.Event(), []
        def lookup():
            try:
                result.append(self.resolver(host, port, type=socket.SOCK_STREAM))
            except OSError:
                result.append(None)
            finally:
                finished.set()
        # A stalled system resolver blocks the run, never creates a retry worker loop.
        threading.Thread(target=lookup, daemon=True, name='announcement-dns').start()
        deadline = time.monotonic() + timeout
        while not finished.wait(min(self.control.policy.wait_slice, max(0,deadline-time.monotonic()))):
            self.control.check()
            if time.monotonic() >= deadline:
                raise Blocked('source_dns_timeout')
        self.control.check()
        if not result[0]:
            raise httpcore.ConnectError('source_dns_unavailable')
        # Reject the whole answer set if any address points inward; no mixed-answer fallback.
        addresses = list(dict.fromkeys(public_address(answer[4][0]) for answer in result[0]))
        if not addresses:
            raise httpcore.ConnectError('source_dns_unavailable')
        return addresses

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.control.check()
        budget = min(timeout if timeout is not None else self.control.policy.connect_timeout, self.control.policy.connect_timeout)
        if budget <= 0:
            raise httpcore.ConnectTimeout('source_connect_timeout')
        started = time.monotonic()
        addresses = self.resolve(host, port, budget)
        for address in addresses:
            self.control.check()
            remaining = budget - (time.monotonic() - started)
            if remaining <= 0:
                raise httpcore.ConnectTimeout('source_connect_timeout')
            try:
                # Numeric target only. ConnectionPool still owns the original Host and SNI.
                return self.connector(address, port, timeout=remaining,
                                      local_address=local_address, socket_options=socket_options)
            except httpcore.ConnectError:
                if address == addresses[-1]:
                    raise


class PublicHTTPTransport(httpx.HTTPTransport):
    def __init__(self, control, backend=None):
        self._pool = httpcore.ConnectionPool(ssl_context=ssl.create_default_context(),
            max_connections=1, max_keepalive_connections=0, retries=0,
            network_backend=backend or PublicNetworkBackend(control))
