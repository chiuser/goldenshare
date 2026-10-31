"""One source prefix, one next-bar forecast, one encoded public response."""
from bisect import bisect_right
from copy import deepcopy
from datetime import date, datetime, time as daytime, timedelta
import hashlib
import json
import time

from sqlalchemy import select
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import InternalForecastResponseDto
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast, precheck_next_bar
from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import FORECAST_SPEC
from src.biz.services.wealth.market.index_detail_xxm.forecast_text import make_display
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection, ProjectionPrecisionError
from src.biz.services.wealth.market.index_detail_xxm.response_projection import project_forecast_response
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import ForecastKernelResult
from .query_service import IndexDetailXxmQueryService, XxmQueryError, _deep_size
from .source import CN_ZONE, ENDPOINTS, expected_through


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def future_calendar(session, period, through, check):
    anchor=date.fromisoformat(through[:10])
    check()
    rows=session.execute(select(TradeCalendar.trade_date,TradeCalendar.is_open).where(
        TradeCalendar.exchange=='SSE',TradeCalendar.trade_date>=anchor,
        TradeCalendar.trade_date<=anchor+timedelta(days=FORECAST_SPEC.future_calendar_days))
        .order_by(TradeCalendar.trade_date).limit(FORECAST_SPEC.future_calendar_days+1)).all()
    check()
    previous=anchor-timedelta(days=1);identity=[]
    slots=(daytime(15),) if period=='day' else ENDPOINTS[int(period[1:])]
    for day,opened in rows:
        check()
        if type(day) is not date or type(opened) is not bool or day!=previous+timedelta(days=1):
            raise XxmQueryError('XXM_SOURCE_CONTRACT_INVALID','未来交易日历存在缺口或字段错误。')
        previous=day;identity.append((day.isoformat(),opened))
        if opened:
            for slot in slots:
                endpoint=day.isoformat() if period=='day' else datetime.combine(day,slot,CN_ZONE).isoformat()
                if endpoint>through:
                    return endpoint,digest(identity)
    raise XxmQueryError('XXM_SOURCE_CONTRACT_INVALID','未来交易日历未覆盖下一端点。')


def _draft(result):
    conditions=[dict(outcome=c.outcome,referenceRole=c.reference_role,
        priceRanges=deepcopy(list(c.price_ranges)),predicates=deepcopy(list(c.predicates))) for c in result.conditions]
    following=[dict(outcome=c.outcome,relatedStructureId=c.related_structure_id,direction=c.direction,
        originWave=deepcopy(c.origin_wave),nextSameColorStart=c.next_same_color_start,nextSameColorCount=c.next_same_color_count,
        priceRanges=deepcopy(list(c.price_ranges)),precisionRanges=deepcopy(list(c.precision_ranges)),
        predicates=deepcopy(list(c.predicates))) for c in result.structure_follow_conditions]
    return conditions,following


def _identity(payload):
    excluded={'forecastId','display','applicabilityText','invalidationText','refreshAfterMs'}
    value=deepcopy({k:v for k,v in payload.items() if k not in excluded})
    for c in [*value['conditions'],*value['structureFollowConditions']]:
        c.pop('id',None)
        for r in c['priceRanges']:
            r.pop('displayLower',None);r.pop('displayUpper',None)
    return digest(value)


def _assemble(*, period, through, as_of, data_status, ordinary, direction, source_id, calendar_id,
              result, prepared, check):
    conditions,following=_draft(result) if result else ([],[])
    references=result.references if result else {'nearest':None,'farther':None}
    payload=dict(tsCode='000001.SH',period=period,forecastVersion=FORECAST_SPEC.forecast_version,
        forecastSpecHash=FORECAST_SPEC.spec_hash,detectorSpecHash=MAIN_SPEC.spec_hash,computedThrough=through,
        requestedAsOf=as_of,mode='REPLAY' if as_of is not None else 'LATEST',dataStatus=data_status,
        ordinaryState=ordinary,direction=direction,targetEndpoint=result.target_endpoint if result else None,
        barsAhead=result.bars_ahead if result else None,status=result.status if result else data_status,
        reasonCode=result.reason_code if result else 'SOURCE_EMPTY' if data_status=='EMPTY' else 'SOURCE_DELAYED',
        sourceInputId=source_id,calendarInputId=calendar_id,precisionPolicy='rounded3_guarded' if period=='day' else 'full_float',
        references=references,selectedReference=result.selected_reference if result else None,
        nearestDecision=result.nearest_decision if result else {'status':'NOT_EVALUATED','reason':None},
        farEvaluated=result.far_evaluated if result else False,conditions=conditions,
        precisionRanges=deepcopy(list(result.precision_ranges)) if result else [],structureFollowConditions=following)
    payload['forecastId']=_identity(payload)
    for c in conditions:
        c['id']=digest({'forecastId':payload['forecastId'],'outcome':c['outcome']})
    for c in following:
        c['id']=digest({'forecastId':payload['forecastId'],'outcome':c['outcome'],'relatedStructureId':c['relatedStructureId']})
    if result is not None:
        display=make_display(result,prepared=prepared,period=period,through=through,mode=payload['mode'],check=check)
    else:
        display=dict(statusLabel='暂无完成行情' if data_status=='EMPTY' else '行情来源滞后',
            targetText='下一根完成收盘条件尚未确定',conditionsText='暂无完成行情，未计算假设点位。' if data_status=='EMPTY' else '来源滞后，不使用旧行情冒充最新预判。',
            asOfText='暂无完成行情' if through is None else f'截至 {through} 收盘')
    payload.update(display=display,refreshAfterMs=FORECAST_SPEC.refresh_after_ms,
        applicabilityText='仅适用于下一根本周期完成收盘；沿用原EMA逐步计算及本次实际近远参照范围。',
        invalidationText='新完成行情到达后重算；零柱不自动失效。旧结构从首次反色起跟踪，单根同色段不终止，首个至少两根同色段结束后停止。近参照失效且远参照未计算时，不代表总体钝化必定消失。')
    check()
    response=InternalForecastResponseDto.model_validate(payload)
    check()
    return response


class IndexDetailXxmForecastQueryService:
    def __init__(self, *, lake_root=None, cache=None):
        self.source=IndexDetailXxmQueryService(lake_root=lake_root,cache=cache)

    def build(self, session, *, period, as_of=None, debug=False, now=None) -> bytes:
        candidate=None
        try:
            with self.source.load_entry(session,period=period,now=now) as (entry,context,open_dates,remaining):
                upper=min(date.fromisoformat(as_of[:10]) if as_of else context.trade_date,context.trade_date)
                expected=expected_through(period,open_dates,context.generated_at,upper)
                if as_of is not None:
                    if expected is None or as_of>expected or upper not in open_dates:
                        raise XxmQueryError('XXM_REQUEST_INVALID','asOf 必须是已完成的开市端点。',400)
                    expected=as_of
                n=bisect_right([b.time for b in entry.processed],expected) if expected else 0
                bars=entry.processed[:n];through=bars[-1].time if bars else None
                status='EMPTY' if not through else 'DELAYED' if expected and through<expected else 'READY'
                ordinary=entry.points[n-1]['ordinaryState'] if n else None
                direction=next(('TOP' if b.hist>0 else 'BOTTOM' for b in reversed(bars) if b.hist!=0),None)
                source_id=entry.fingerprints[n-1] if n else None
                check=remaining;prepared=result=None;calendar_id=None;cached=None
                if status=='READY':
                    deadline=time.perf_counter()+FORECAST_SPEC.forecast_compute_budget_ms/1000
                    def check():
                        left=min(remaining(),deadline-time.perf_counter())
                        if left<=0:
                            raise XxmQueryError('XXM_BUDGET_EXCEEDED','下一根预判超过计算预算。',503)
                        return left
                    calculator=entry.calculator_at(n,check)
                    prepared=precheck_next_bar(calculator,check)
                    direction=prepared.direction
                    if prepared.stop_reason and not prepared.following_structures:
                        result=ForecastKernelResult('NO_CANDIDATE',prepared.stop_reason,None,None,prepared.references,None,
                                                    prepared.nearest_decision,False,(),(),())
                    else:
                        try:
                            projection=recover_projection(bars,period,check)
                        except ProjectionPrecisionError as exc:
                            if exc.reason!='CALIBRATION_FAILED': raise
                            result=ForecastKernelResult('PRECISION_PENDING',exc.reason,None,None,prepared.references,None,
                                                        prepared.nearest_decision,False,(),(),())
                        else:
                            endpoint,calendar_id=future_calendar(session,period,through,check)
                            key=(id(session.get_bind()),self.source.lake_identity,period,MAIN_SPEC.spec_hash,
                                 FORECAST_SPEC.spec_hash,source_id,expected,as_of,calendar_id)
                            cached=self.source.cache.get_forecast(key,check=check)
                            if cached is None:
                                result=forecast(calculator,projection,endpoint,check,prepared=prepared)
                response=(InternalForecastResponseDto.model_validate(cached.model_dump()) if cached is not None else
                    _assemble(period=period,through=through,as_of=as_of,data_status=status,ordinary=ordinary,direction=direction,
                        source_id=source_id,calendar_id=calendar_id,result=result,prepared=prepared,check=check))
                check()
                public=project_forecast_response(response,debug=debug)
                check()
                body=public.model_dump_json().encode('utf-8')
                if len(body)>FORECAST_SPEC.max_response_bytes:
                    raise XxmQueryError('XXM_BUDGET_EXCEEDED','预测响应超过预算。',503)
                check()
                if cached is None and result is not None and result.target_endpoint is not None:
                    clone=response.model_copy(deep=True);size=_deep_size(clone);check()
                    candidate=(key,clone,size)
            # load_entry's final remaining() must run BEFORE any forecast publish.
            check()
            if candidate is not None:
                self.source.cache.put_forecast(*candidate,check=check)
            return body
        except XxmQueryError:
            raise
        except TimeoutError as exc:
            raise XxmQueryError('XXM_BUDGET_EXCEEDED','下一根预判超过预算。',503) from exc
        except (ValueError,TypeError) as exc:
            raise XxmQueryError('XXM_SOURCE_CONTRACT_INVALID','下一根预判来源或结果合同不一致。') from exc
