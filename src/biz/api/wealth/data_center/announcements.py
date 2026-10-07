from pydantic import ValidationError
from fastapi import APIRouter,Depends,Query,Request
from fastapi.responses import JSONResponse

from src.foundation.config.announcement_archive import DataCenterPolicy,announcements_enabled
from src.foundation.config.settings import get_settings
from src.foundation.clients.announcement_archive.core import Blocked
from src.foundation.clients.announcement_archive.budget import read_budget
from src.biz.schemas.wealth.data_center.announcements import AnnouncementQueryRequest,QueryResultDto,CompanyResultDto
from src.biz.services.wealth.data_center.errors import DataCenterError,mapped_error

router=APIRouter(prefix='/wealth/data-center/announcements',tags=['wealth-announcements'])


def query_service(request:Request):
    if not announcements_enabled(get_settings()):
        raise DataCenterError('DC_MODULE_UNAVAILABLE','当前部署不提供上市公司公告模块',404)
    runtime=getattr(request.app.state,'announcement_source',None)
    if runtime is None:
        raise DataCenterError('DC_SOURCE_UNAVAILABLE','本地公告查询正在准备或来源不可用')
    try:return runtime.service()
    except Blocked as error:raise mapped_error(str(error)) from None


def parameters_only(request,allowed):
    pairs=request.query_params.multi_items()
    if set(request.query_params)-allowed or len(pairs)!=len(request.query_params):
        raise DataCenterError('DC_REQUEST_INVALID','公告查询包含未知或重复参数',422)


def respond(operation,model=None):
    try:
        with read_budget(DataCenterPolicy().api_seconds):
            result,status=operation()
    except ValidationError:
        raise DataCenterError('DC_REQUEST_INVALID','公告查询参数不合法，请检查日期或筛选条件',422) from None
    except Blocked as error:
        raise mapped_error(str(error)) from None
    if model:
        try:
            result=model.model_validate(result).model_dump(exclude_none=False)
        except ValidationError:
            raise DataCenterError('DC_QUERY_FAILED','公告查询结果暂无法读取') from None
    return JSONResponse(result,status_code=status)


@router.get('/context')
def context(request:Request,service=Depends(query_service)):
    parameters_only(request,set())
    return respond(lambda:(service.context(),200))


@router.post('/queries',response_model=QueryResultDto,responses={202:{'model':QueryResultDto}})
def create_query(request:Request,body:AnnouncementQueryRequest,service=Depends(query_service)):
    parameters_only(request,set())
    return respond(lambda:service.create(body),QueryResultDto)


@router.get('/queries/{query_id}',response_model=QueryResultDto,responses={202:{'model':QueryResultDto}})
def read_query(request:Request,query_id:str,page:int=Query(default=1,ge=1),service=Depends(query_service)):
    parameters_only(request,{'page'})
    return respond(lambda:service.read(query_id,page),QueryResultDto)


@router.get('/companies',response_model=CompanyResultDto,responses={202:{'model':CompanyResultDto}})
def companies(request:Request,keyword:str=Query(default='',max_length=DataCenterPolicy().keyword_limit),
              startDate:str|None=Query(None,pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'),
              endDate:str|None=Query(None,pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'),service=Depends(query_service)):
    parameters_only(request,{'keyword','startDate','endDate'})
    return respond(lambda:service.companies(keyword,AnnouncementQueryRequest(startDate=startDate,endDate=endDate)),CompanyResultDto)
