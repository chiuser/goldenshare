from __future__ import annotations

from typing import Protocol

from qtf.modules.sector.input_contract import SectorInputRequest, SectorInputSnapshot


class SectorInputSource(Protocol):
    def read(self, request: SectorInputRequest) -> SectorInputSnapshot: ...
