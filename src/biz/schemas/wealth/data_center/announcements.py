from datetime import date
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator,field_validator
from src.foundation.config.announcement_archive import DataCenterPolicy


class AnnouncementQueryRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    startDate: date | None = None
    endDate: date | None = None
    tsCode: str | None = Field(default=None,pattern=r'^\d{6}\.(SH|SZ|BJ)$')
    titleKeyword: str = Field(default='',max_length=DataCenterPolicy().title_limit)
    downloadStatus: Literal['all','downloaded','undownloaded'] = 'all'

    @field_validator('startDate','endDate',mode='before')
    @classmethod
    def iso_date_only(cls,value):
        import re
        if value is not None and not isinstance(value,date) and (not isinstance(value,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value)):
            raise ValueError('expected_YYYY-MM-DD')
        return value

    @model_validator(mode='after')
    def date_range(self):
        if self.startDate and self.endDate and self.endDate<self.startDate:
            raise ValueError('date_range_reversed')
        return self


class ContractDto(BaseModel):
    model_config=ConfigDict(extra='forbid')


class PageStateDto(ContractDto):
    status: Literal['preparing','ready','empty','error']
    code: str|None
    message: str|None
    asOfTime: str


class AnnouncementRowDto(ContractDto):
    recordKey: str
    annDate: str
    tsCode: str|None
    companyName: str
    companyNameSource: Literal['master','announcement','code']
    title: str|None
    sourceUrl: str|None
    downloadStatus: Literal['downloaded','undownloaded']|None
    statusCheckedAt: str|None


class QueryConditionsDto(ContractDto):
    startDate: str
    endDate: str
    tsCode: str|None
    titleKeyword: str
    downloadStatus: Literal['all','downloaded','undownloaded']


class QueryPreparationDto(ContractDto):
    stage: Literal['readingSource','checkingStatus','counting']
    artifactsChecked: int
    datesScanned: int
    datesTotal: int
    recordsScanned: int


class QueryResultDto(ContractDto):
    queryId: str
    pageState: PageStateDto
    sourceVersion: str|None = Field(pattern=r'^[0-9a-f]{64}$')
    conditions: QueryConditionsDto
    items: list[AnnouncementRowDto]=Field(max_length=50)
    total: int|None
    page: int
    pageSize: Literal[50]
    hasPrevious: bool
    hasNext: bool
    downloadStatusAvailable: bool
    preparation: QueryPreparationDto|None


class CompanyCandidateDto(ContractDto):
    tsCode: str
    name: str
    initials: str|None
    matchedAlias: str|None
    nameSource: Literal['master','announcement','code']
    matchKind: Literal['exactCode','codePrefix','name','initials','alias']


class CompanyResultDto(ContractDto):
    keyword: str
    items: list[CompanyCandidateDto]=Field(max_length=20)
    hasMore: bool|None
    pageState: PageStateDto|None=None
    preparation: QueryPreparationDto|None=None
    queryId: str|None=None
