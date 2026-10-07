"""Download controls accept intents only; all progress and qualification are backend facts."""
from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import Field,field_validator,model_validator
from src.foundation.clients.announcement_archive.core import DownloadOptions
from .announcements import ContractDto,QueryPreparationDto,AnnouncementQueryRequest


class PreviewRequest(ContractDto):
    startDate:date
    endDate:date
    intervalSeconds:float=Field(default=DownloadOptions.interval_seconds,ge=0,allow_inf_nan=False)

    @field_validator('startDate','endDate',mode='before')
    @classmethod
    def dates(cls,value):return AnnouncementQueryRequest.iso_date_only(value)

    @field_validator('intervalSeconds',mode='before')
    @classmethod
    def interval(cls,value):
        if isinstance(value,bool) or not isinstance(value,(int,float)):raise ValueError('expected_finite_number')
        return value

    @model_validator(mode='after')
    def range(self):
        if self.endDate<self.startDate:raise ValueError('date_range_reversed')
        return self


class CreateRunRequest(ContractDto):previewId:UUID


class RetryRequest(ContractDto):
    scope:Literal['allFailed','singleFailed']
    artifactKey:str|None=Field(default=None,pattern=r'^[0-9a-f]{64}$')
    @model_validator(mode='after')
    def single(self):
        if (self.scope=='singleFailed')!=(self.artifactKey is not None):raise ValueError('retry_scope_invalid')
        return self


class RecheckRequest(ContractDto):kind:Literal['volume','localSource','remoteSource']
class EmptyRequest(ContractDto):pass
class PublicError(ContractDto):code:str;message:str


class PreviewPreparation(ContractDto):
    datesScanned:int
    datesTotal:int
    recordsScanned:int


class PreviewDto(ContractDto):
    previewId:str
    state:Literal['preparing','ready','empty','error','cancelled']
    startDate:str
    endDate:str
    intervalSeconds:float
    recordCount:int|None
    artifactCount:int|None
    missingUrlCount:int|None
    reusableEstimate:int|None
    downloadEstimate:int|None
    canStart:bool
    expiresAt:str|None
    preparation:PreviewPreparation
    error:PublicError|None


class TaskPreparation(ContractDto):datesScanned:int;datesTotal:int;currentDate:str|None
class CurrentFile(ContractDto):
    artifactKey:str
    annDate:str
    tsCode:str|None
    companyName:str
    title:str|None
    attemptNumber:int
    maxAttempts:Literal[3]
    bytesReceived:int
    bytesTotal:int|None
    transferState:Literal['receiving','verifying']
class TaskWait(ContractDto):kind:Literal['interval','backoff','cooldown'];until:str
class TaskActions(ContractDto):canStop:bool;canContinue:bool;canRetryFailed:bool;canCreateNew:bool;canRecheck:bool;reason:str|None
class TaskCheck(ContractDto):state:Literal['checking','passed','blocked','unknown','cancelled'];kind:Literal['volume','localSource','remoteSource'];code:str|None;updatedAt:str


class TaskDto(ContractDto):
    runId:str
    rootRunId:str
    retryOfRunId:str|None
    batchKind:Literal['date','retry']
    phase:Literal['preparing','downloading','stopping','completed','partial_failed','cancelled','blocked','stopped','interrupted']
    revision:int
    startDate:str
    endDate:str
    intervalSeconds:float
    archiveLocation:str
    createdAt:str
    startedAt:str|None
    finishedAt:str|None
    recordCount:int
    missingUrlCount:int
    total:int|None
    processed:int
    succeeded:int
    reused:int
    failed:int
    remaining:int|None
    percent:float|None
    unresolvedFailureCount:int
    preparation:TaskPreparation
    current:CurrentFile|None
    wait:TaskWait|None
    businessUpdatedAt:str
    heartbeatAt:str
    etaSeconds:None
    blockedReason:PublicError|None
    actions:TaskActions
    check:TaskCheck|None


class FileError(PublicError):httpStatus:int|None
class RunFileDto(ContractDto):
    artifactKey:str
    representativeRecordKey:str|None
    annDate:str|None
    tsCode:str|None
    companyName:str
    title:str|None
    result:Literal['pending','processing','succeeded','reused','failed']
    attempts:int
    lastError:FileError|None
    canRetry:bool
class FilesDto(ContractDto):runId:str;items:list[RunFileDto]=Field(max_length=50);nextCursor:str|None
class HistoryItem(ContractDto):
    runId:str
    startDate:str|None
    endDate:str|None
    phase:str
    createdAt:str|None
    total:int
    succeeded:int
    reused:int
    failed:int
    rootRunId:str
    retryOfRunId:str|None
class HistoryDto(ContractDto):currentRunId:str|None;items:list[HistoryItem]=Field(max_length=20);nextCursor:str|None
