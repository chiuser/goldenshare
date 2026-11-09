from src.biz.schemas.wealth.market.index_detail_xxm_forecast import InternalForecastResponseDto, ForecastResponseDto
from .response_projection import forecast_fields, signal_fields


def _wave(wave):
    return None if wave is None else dict(sign=wave['sign'],start=wave['start'],end=wave['end'],
        count=wave['count'],price=wave['price'],dif=wave['dif'],priceAt=wave['price_at'],difAt=wave['dif_at'])


def project_debug_signal(internal):
    from src.biz.schemas.wealth.market.index_detail_xxm_debug import XxmDebugResponseDto

    payload = signal_fields(internal)
    structures=[]
    for record in internal.structures:
        value=record.model_dump(); value['originWave']=_wave(value['originWave']); structures.append(value)
    payload['debug']=dict(sourceInputId=internal.source.inputId,
        points=[dict(time=p.time,activeReference=p.activeReference.model_dump() if p.activeReference else None,
                     activeStructureId=p.activeStructureId) for p in internal.points],
        events=[{k:(getattr(e,k).model_dump() if k=='eventReference' else getattr(e,k)) for k in
                 ('id','route','fromState','eventReference','relatedStructureId')} for e in internal.events],structures=structures)
    return XxmDebugResponseDto.model_validate(payload)


def project_debug_forecast(internal):
    from src.biz.schemas.wealth.market.index_detail_xxm_forecast_debug import ForecastDebugResponseDto

    payload = forecast_fields(internal)
    details={k:getattr(internal,k) for k in InternalForecastResponseDto.model_fields if k not in ForecastResponseDto.model_fields}
    for key in ('references','nearestDecision'):
        details[key]=details[key].model_dump()
    for key in ('conditions','precisionRanges'):
        details[key]=[v.model_dump() for v in details[key]]
    details['structureFollowConditions']=[]
    for item in internal.structureFollowConditions:
        value=item.model_dump();value['originWave']=_wave(value['originWave']);details['structureFollowConditions'].append(value)
    payload['debug']=details
    return ForecastDebugResponseDto.model_validate(payload)
