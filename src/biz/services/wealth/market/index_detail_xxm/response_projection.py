"""Project validated recognition and forecast facts into their public fields."""
from goldenshare_technical_indicators.xxm.event_display import event_display_flags

from src.biz.schemas.wealth.market.index_detail_xxm import InternalXxmResponseDto, XxmResponseDto
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import InternalForecastResponseDto, ForecastResponseDto


def signal_fields(internal: InternalXxmResponseDto):
    if not isinstance(internal, InternalXxmResponseDto):
        raise ValueError('Expected a validated InternalXxmResponseDto')
    flags=event_display_flags([e.model_dump() for e in internal.events])
    source={k:getattr(internal.source,k) for k in ('kind','startTime','computedThrough','initialHistoryIncomplete','indicatorVersion')}
    payload=dict(tsCode=internal.tsCode,period=internal.period,algorithmVersion=internal.algorithmVersion,
        specHash=internal.specHash,source=source,meta=internal.meta.model_dump(),dataStatus=internal.dataStatus.model_dump(),
        points=[{k:getattr(p,k) for k in ('time','close','dif','dea','hist','ordinaryState','ordinaryDirection')} for p in internal.points],
        events=[dict(id=e.id,time=e.time,direction=e.direction,type=e.type,displayOnChart=flags[e.id]) for e in internal.events])
    return payload


def project_xxm_response(internal: InternalXxmResponseDto):
    return XxmResponseDto.model_validate(signal_fields(internal))


def forecast_fields(internal: InternalForecastResponseDto):
    if not isinstance(internal, InternalForecastResponseDto):
        raise ValueError('Expected a validated InternalForecastResponseDto')
    payload = {name: getattr(internal, name) for name in ForecastResponseDto.model_fields}
    payload["display"] = internal.display.model_dump()
    return payload


def project_forecast_response(internal: InternalForecastResponseDto):
    return ForecastResponseDto.model_validate(forecast_fields(internal))
