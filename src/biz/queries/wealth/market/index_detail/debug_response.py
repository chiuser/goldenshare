from src.biz.schemas.wealth.market.index_detail_debug import (
    IndexDetailDebugInfoDto,
    IndexDetailKlineDebugResponseDto,
    IndexDetailModuleDebugDto,
    IndexDetailPageInitDebugResponseDto,
    IndexDetailWeightsDebugResponseDto,
)
from src.biz.services.wealth.market.index_detail.index_detail_exception_builder import IndexDetailExceptionBuilder
from src.biz.services.wealth.market.index_detail.index_detail_status_resolver import IndexDetailStatusResolver


def _module(module, status, row_count, missing_count):
    return IndexDetailModuleDebugDto(
        module=module, status=status.status, expectedTradeDate=status.expectedTradeDate,
        observedTradeDate=status.observedTradeDate, rowCount=row_count, missingCount=missing_count,
    )


def page_init_response(response, factor_missing_count, daily_basic_missing_count):
    builder = IndexDetailExceptionBuilder()
    status = response.dataStatus
    day = response.asOfTradeDate
    breadth = response.constituentBreadth
    exceptions = []
    if day is None:
        exceptions.append(builder.source_empty(module="indexDetailPageInit", message="指数日线无可用数据"))
        modules = [_module(name, status, 0, None) for name in ("pageInit", "quote", "dailyBasic", "breadth")]
    else:
        if factor_missing_count:
            exceptions.append(builder.factor_partial(module="indexDetailPageInit", message="指数同日因子量额缺失"))
        if daily_basic_missing_count:
            exceptions.append(builder.daily_basic_partial(message="指数同日基本指标缺失"))
        if breadth is None:
            exceptions.append(builder.weight_empty(module="indexDetailPageInit", message="指数无可用权重批次"))
        if day < status.expectedTradeDate:
            exceptions.append(builder.source_delayed(module="indexDetailPageInit", message="指数日线观测日期落后于期望日期"))

        resolve = IndexDetailStatusResolver.resolve
        quote_status = resolve(expected_trade_date=status.expectedTradeDate, observed_trade_date=day,
                               empty=False, partial=factor_missing_count > 0)
        has_basic = response.dailyBasic is not None
        basic_status = resolve(expected_trade_date=day, observed_trade_date=day if has_basic else None,
                               empty=not has_basic, partial=has_basic and daily_basic_missing_count > 0)
        breadth_status = breadth.dataStatus if breadth is not None else resolve(
            expected_trade_date=day, observed_trade_date=None, empty=True, partial=False,
        )
        modules = [
            _module("pageInit", status, 1, None),
            _module("quote", quote_status, 1, factor_missing_count),
            _module("dailyBasic", basic_status, int(has_basic), daily_basic_missing_count),
            _module("breadth", breadth_status, breadth.totalConstituentCount if breadth else 0,
                    breadth.missingCount if breadth else None),
        ]
    return IndexDetailPageInitDebugResponseDto(
        **response.model_dump(exclude={"debugInfo"}),
        debugInfo=IndexDetailDebugInfoDto(modules=modules, exceptions=exceptions),
    )


def kline_response(response, missing_count):
    builder = IndexDetailExceptionBuilder()
    status = response.dataStatus
    exceptions = []
    if not response.bars:
        exceptions.append(builder.source_empty(module="indexDetailKline", message="指数因子日线无可用数据"))
    else:
        if missing_count:
            exceptions.append(builder.factor_partial(module="indexDetailKline", message="指数日线因子存在缺失或落后"))
        if (not hasattr(response.meta, "nextEndDate")
                and status.observedTradeDate < status.expectedTradeDate):
            exceptions.append(builder.source_delayed(module="indexDetailKline", message="指数因子观测日期落后于查询上界"))
    return IndexDetailKlineDebugResponseDto(
        **response.model_dump(exclude={"debugInfo"}),
        debugInfo=IndexDetailDebugInfoDto(
            modules=[_module("kline", status, response.meta.count, missing_count)], exceptions=exceptions,
        ),
    )


def weights_response(response, anchor_missing):
    builder = IndexDetailExceptionBuilder()
    status = response.dataStatus
    missing_count = None
    exceptions = []
    if response.weightTradeDate is None:
        if anchor_missing:
            exceptions.append(builder.source_empty(module="indexDetailWeights", message="指数日线无可用数据"))
        else:
            exceptions.append(builder.weight_empty(module="indexDetailWeights", message="指数无可用权重批次"))
    else:
        missing_count = response.coverage.contributionMissingCount
        if anchor_missing:
            exceptions.append(builder.weight_contribution_partial(message="指数昨收缺失，无法计算成分贡献点"))
        if response.contributionTradeDate < status.expectedTradeDate:
            exceptions.append(builder.source_delayed(module="indexDetailWeights", message="权重贡献日期落后于期望日期"))
    return IndexDetailWeightsDebugResponseDto(
        **response.model_dump(exclude={"debugInfo"}),
        debugInfo=IndexDetailDebugInfoDto(
            modules=[_module("weights", status, len(response.rows), missing_count)], exceptions=exceptions,
        ),
    )
