"""Local archive command port; implementations are supplied by the composition root."""
from typing import Protocol


class ArchiveExecutionPort(Protocol):
    def submit(self,kind:str,payload:dict,key:str|None=None,actor:str|None=None)->str: ...
    def close(self)->None: ...
