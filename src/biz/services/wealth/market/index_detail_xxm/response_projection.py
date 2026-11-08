"""Public projections of validated facts. No market reads or signal evaluation."""
from src.biz.schemas.wealth.market.index_detail_xxm import (
    InternalXxmResponseDto, XxmResponseDto, XxmDebugResponseDto,
)
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import (
    InternalForecastResponseDto, ForecastResponseDto, ForecastDebugResponseDto,
)


def event_display_flags(events):
    activations = {(event["time"], event["direction"]): event for event in events
                   if event["type"] == "DULL" and event["route"] == "activation"}
    flags = {}
    for event in events:
        activation = activations.get((event["time"], event["direction"]))
        hide = event["type"] == "CANCEL" and activation is not None and (
            event["route"] == "structure_price_break"
            or (event["route"] == "dif_break" and event["fromState"] == "STRUCTURE"
                and event["relatedStructureId"] is not None and activation["fromState"] == "NONE"
                and activation["relatedStructureId"] is None
                and event["eventReference"] != activation["eventReference"])
        )
        flags[event["id"]] = not hide
    return flags


def _wave(wave):
    return None if wave is None else dict(sign=wave['sign'],start=wave['start'],end=wave['end'],
        count=wave['count'],price=wave['price'],dif=wave['dif'],priceAt=wave['price_at'],difAt=wave['dif_at'])


def project_xxm_response(internal: InternalXxmResponseDto, *, debug: bool):
    """Project an upstream-validated internal model, unchanged since validation."""
    if type(debug) is not bool:
        raise ValueError('Debug must be a boolean')
    if not isinstance(internal, InternalXxmResponseDto):
        raise ValueError('Expected a validated InternalXxmResponseDto')
    flags=event_display_flags([e.model_dump() for e in internal.events])
    source={k:getattr(internal.source,k) for k in ('kind','startTime','computedThrough','initialHistoryIncomplete','indicatorVersion')}
    payload=dict(tsCode=internal.tsCode,period=internal.period,algorithmVersion=internal.algorithmVersion,
        specHash=internal.specHash,source=source,meta=internal.meta.model_dump(),dataStatus=internal.dataStatus.model_dump(),
        points=[{k:getattr(p,k) for k in ('time','close','dif','dea','hist','ordinaryState','ordinaryDirection')} for p in internal.points],
        events=[dict(id=e.id,time=e.time,direction=e.direction,type=e.type,displayOnChart=flags[e.id]) for e in internal.events])
    if debug:
        structures=[]
        for record in internal.structures:
            value=record.model_dump(); value['originWave']=_wave(value['originWave']); structures.append(value)
        payload['debug']=dict(sourceInputId=internal.source.inputId,
            points=[dict(time=p.time,activeReference=p.activeReference.model_dump() if p.activeReference else None,
                         activeStructureId=p.activeStructureId) for p in internal.points],
            events=[{k:(getattr(e,k).model_dump() if k=='eventReference' else getattr(e,k)) for k in
                     ('id','route','fromState','eventReference','relatedStructureId')} for e in internal.events],structures=structures)
    return (XxmDebugResponseDto if debug else XxmResponseDto).model_validate(payload)


def project_forecast_response(internal: InternalForecastResponseDto, *, debug: bool):
    """Project an upstream-validated internal model, unchanged since validation."""
    if type(debug) is not bool:
        raise ValueError('Debug must be a boolean')
    if not isinstance(internal, InternalForecastResponseDto):
        raise ValueError('Expected a validated InternalForecastResponseDto')
    # Only public fields are traversed for an ordinary response.
    payload={k:getattr(internal,k) for k in ForecastResponseDto.model_fields}
    payload['display']=internal.display.model_dump()
    if debug:
        details={k:getattr(internal,k) for k in InternalForecastResponseDto.model_fields if k not in ForecastResponseDto.model_fields}
        for key in ('references','nearestDecision'):
            details[key]=details[key].model_dump()
        for key in ('conditions','precisionRanges'):
            details[key]=[v.model_dump() for v in details[key]]
        details['structureFollowConditions']=[]
        for item in internal.structureFollowConditions:
            value=item.model_dump();value['originWave']=_wave(value['originWave']);details['structureFollowConditions'].append(value)
        payload['debug']=details
    return (ForecastDebugResponseDto if debug else ForecastResponseDto).model_validate(payload)
