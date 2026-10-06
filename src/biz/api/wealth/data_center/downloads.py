from uuid import UUID
from fastapi import APIRouter,Depends,Header,Query,Request,Body
from src.foundation.clients.announcement_archive.core import Blocked
from src.foundation.config.announcement_archive import announcements_enabled
from src.foundation.config.settings import get_settings
from src.biz.schemas.wealth.data_center.downloads import PreviewRequest,CreateRunRequest,RetryRequest,RecheckRequest,EmptyRequest,PreviewDto,TaskDto,HistoryDto,FilesDto
from src.biz.services.wealth.data_center.errors import DataCenterError,mapped_download_error
from .announcements import respond,parameters_only

router=APIRouter(prefix='/wealth/data-center/announcements',tags=['wealth-announcement-downloads'])


def download_service(request:Request):
    if not announcements_enabled(get_settings()):raise DataCenterError('DC_MODULE_UNAVAILABLE','当前部署不提供上市公司公告模块',404)
    service=getattr(request.app.state,'announcement_download',None)
    if service is None:raise DataCenterError('DC_LEDGER_FAILED','本地公告下载能力尚未就绪')
    return service


def response(operation,model):
    def adapted():
        try:return operation()
        except Blocked as error:raise mapped_download_error(str(error)) from None
    return respond(adapted,model)


@router.post('/previews',response_model=PreviewDto,responses={202:{'model':PreviewDto}})
def create_preview(request:Request,body:PreviewRequest,service=Depends(download_service)):
    parameters_only(request,set());return response(lambda:service.create_preview(body),PreviewDto)

@router.get('/previews/{preview_id}',response_model=PreviewDto,responses={202:{'model':PreviewDto}})
def preview(request:Request,preview_id:UUID,service=Depends(download_service)):
    parameters_only(request,set());return response(lambda:service.preview(preview_id.hex),PreviewDto)

@router.post('/previews/{preview_id}/stop',response_model=PreviewDto,responses={202:{'model':PreviewDto}})
def stop_preview(request:Request,preview_id:UUID,body:EmptyRequest=Body(default=EmptyRequest()),service=Depends(download_service)):
    parameters_only(request,set());return response(lambda:service.stop_preview(preview_id.hex),PreviewDto)

@router.post('/runs',response_model=TaskDto,responses={202:{'model':TaskDto}})
def create_run(request:Request,body:CreateRunRequest,key:UUID=Header(alias='Idempotency-Key'),service=Depends(download_service)):
    parameters_only(request,set());return response(lambda:service.command('create',dict(previewId=body.previewId.hex),str(key),getattr(request.state,'announcement_actor',None)),TaskDto)

@router.get('/runs',response_model=HistoryDto,responses={202:{'model':HistoryDto}})
def history(request:Request,cursor:str|None=Query(None,pattern=r'^[1-9][0-9]{0,17}$'),limit:int=Query(20,ge=1,le=20),service=Depends(download_service)):
    parameters_only(request,{'cursor','limit'});return response(lambda:(service.runs.history(cursor,limit),200),HistoryDto)

@router.get('/runs/{run_id}',response_model=TaskDto,responses={202:{'model':TaskDto}})
def task(request:Request,run_id:UUID,service=Depends(download_service)):
    parameters_only(request,set());return response(lambda:(service.runs.task(run_id.hex),200),TaskDto)

@router.get('/runs/{run_id}/files',response_model=FilesDto,responses={202:{'model':FilesDto}})
def files(request:Request,run_id:UUID,result:str=Query('all',pattern=r'^(all|failed|pending|succeeded|reused)$'),cursor:str|None=Query(None,pattern=r'^[0-9a-f]{64}$'),limit:int=Query(50,ge=1,le=50),service=Depends(download_service)):
    parameters_only(request,{'result','cursor','limit'});return response(lambda:(service.runs.files(run_id.hex,result,cursor,limit),200),FilesDto)

@router.post('/runs/{run_id}/stop',response_model=TaskDto,responses={202:{'model':TaskDto}})
def stop(request:Request,run_id:UUID,body:EmptyRequest=Body(default=EmptyRequest()),service=Depends(download_service)):
    parameters_only(request,set());return response(lambda:service.stop(run_id.hex),TaskDto)

@router.post('/runs/{run_id}/continue',response_model=TaskDto,responses={202:{'model':TaskDto}})
def continue_run(request:Request,run_id:UUID,body:EmptyRequest=Body(default=EmptyRequest()),key:UUID=Header(alias='Idempotency-Key'),service=Depends(download_service)):
    parameters_only(request,set());return response(lambda:service.command('continue',dict(runId=run_id.hex),str(key),getattr(request.state,'announcement_actor',None)),TaskDto)

@router.post('/runs/{run_id}/retries',response_model=TaskDto,responses={202:{'model':TaskDto}})
def retry(request:Request,run_id:UUID,body:RetryRequest,key:UUID=Header(alias='Idempotency-Key'),service=Depends(download_service)):
    parameters_only(request,set());return response(lambda:service.command('retry',dict(runId=run_id.hex,**body.model_dump()),str(key),getattr(request.state,'announcement_actor',None)),TaskDto)

@router.post('/runs/{run_id}/recheck',response_model=TaskDto,responses={202:{'model':TaskDto}})
def recheck(request:Request,run_id:UUID,body:RecheckRequest,service=Depends(download_service)):
    parameters_only(request,set());return response(lambda:service.command('recheck',dict(runId=run_id.hex,kind=body.kind)),TaskDto)


@router.get('/runs/{run_id}/related',response_model=HistoryDto)
def related(request:Request,run_id:UUID,cursor:str|None=Query(None,pattern=r'^[1-9][0-9]{0,17}$'),limit:int=Query(20,ge=1,le=20),service=Depends(download_service)):
    parameters_only(request,{'cursor','limit'});return response(lambda:(service.runs.history(cursor,limit,related_to=run_id.hex),200),HistoryDto)
