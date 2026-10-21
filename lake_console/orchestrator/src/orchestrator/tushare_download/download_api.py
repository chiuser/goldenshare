"""Business-facing composition. Credentials and request policy are not call parameters."""

from __future__ import annotations

from time import sleep

from .configuration import ConfigurationLoader
from .contract_registry import ContractRegistry
from .contracts import CONTRACTS
from .dataset_transport_mapping import BINDINGS, DatasetTransportMapping
from .download_session import DownloadSession
from .source_transport import SystemClock, transport_factory


class TushareDownloader:
    def __init__(self):
        self._initialize(
            ConfigurationLoader.load_configuration(),
            ContractRegistry(CONTRACTS),
            DatasetTransportMapping(BINDINGS),
            transport_factory,
            SystemClock(),
            sleep,
        )

    def _initialize(self, config, registry, bindings, factory, clock, sleep_fn):
        self._config, self._registry, self._bindings = config, registry, bindings
        self._transport_factory, self._clock, self._sleep_fn = factory, clock, sleep_fn
        self._active_session = None

    @classmethod
    def load(cls):
        return cls()

    def download(self, task, *, control=None, on_progress=None):
        return DownloadSession(self, task, control, on_progress)


def _build_downloader(config, registry, bindings, transport_factory, clock, sleep_fn):
    downloader = TushareDownloader.__new__(TushareDownloader)
    downloader._initialize(
        config, registry, bindings, transport_factory, clock, sleep_fn
    )
    return downloader
