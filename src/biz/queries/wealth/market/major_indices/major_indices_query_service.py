from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.major_indices import (
    MajorIndexRowDto,
    MajorIndicesDebugInfoDto,
    MajorIndicesDefinitionDto,
    MajorIndicesPayloadDto,
    MajorIndicesResponseDto,
    ModuleStatusItemDto,
    PageStatusDto,
    SubjectRefDto,
    TradingDayDto,
)
from src.biz.services.wealth.config import (
    MajorIndicesStrategyPayload,
    StrategyConfigNotFoundError,
    StrategyConfigService,
    StrategyConfigValidationError,
)
from src.biz.services.wealth.market.major_indices.major_indices_exception_builder import MajorIndicesExceptionBuilder
from src.biz.services.wealth.market.major_indices.major_indices_status_resolver import MajorIndicesStatusResolver
from .major_indices_query import MajorIndicesQuery, MajorIndicesSnapshotRow
from .major_indices_state_query import MajorIndicesStateQuery, MajorIndicesTradingDayContext


_DEFAULT_DEFINITION_KEY = "CN_A_MAJOR_INDICES_V1"
_DEFAULT_INDEX_CODES: tuple[str, ...] = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "899050.BJ",
    "000510.SH",
    "000016.SH",
)


@dataclass(frozen=True, slots=True)
class MajorIndicesDefinition:
    definition_key: str
    version: str
    index_codes: tuple[str, ...]


class MarketMajorIndicesQueryService:
    """Orchestrate major indices module response assembly."""

    def __init__(self) -> None:
        self._config_service = StrategyConfigService()
        self._state_query = MajorIndicesStateQuery()
        self._query = MajorIndicesQuery()
        self._status_resolver = MajorIndicesStatusResolver()
        self._exception_builder = MajorIndicesExceptionBuilder()

    def build_major_indices(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> MajorIndicesResponseDto:
        exceptions = []
        trading_day_context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )

        try:
            definition = self._load_definition(market=market)
        except StrategyConfigNotFoundError as exc:
            exceptions.append(self._exception_builder.config_missing(message=str(exc)))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                index_codes=_DEFAULT_INDEX_CODES,
                debug=debug,
                exceptions=exceptions,
            )
        except StrategyConfigValidationError as exc:
            exceptions.append(self._exception_builder.config_invalid(message=str(exc)))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                index_codes=_DEFAULT_INDEX_CODES,
                debug=debug,
                exceptions=exceptions,
            )
        except ValueError as exc:
            exceptions.append(self._exception_builder.config_invalid(message=str(exc)))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                index_codes=_DEFAULT_INDEX_CODES,
                debug=debug,
                exceptions=exceptions,
            )

        try:
            source_state = self._state_query.load_source_state(session, index_codes=list(definition.index_codes))
            snapshot_rows = self._query.load_snapshot_rows(
                session,
                trade_date=trading_day_context.expected_trade_date,
                index_codes=list(definition.index_codes),
            )
            index_names = self._query.load_index_names(session, index_codes=list(definition.index_codes))
        except Exception as exc:  # noqa: BLE001
            exceptions.append(self._exception_builder.query_failed(message=f"major indices query failed: {exc}"))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                index_codes=definition.index_codes,
                definition=definition,
                debug=debug,
                exceptions=exceptions,
            )

        status_result = self._status_resolver.resolve(
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=source_state.observed_trade_date,
            row_count=len(snapshot_rows),
            expected_count=len(definition.index_codes),
            as_of_time=trading_day_context.as_of_time,
        )
        if status_result.module_status.status == "DELAYED" and status_result.module_status.observedTradeDate is not None:
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="index source date lagged",
                    expected_trade_date=status_result.module_status.expectedTradeDate.isoformat(),
                    observed_trade_date=status_result.module_status.observedTradeDate.isoformat(),
                )
            )
        if len(snapshot_rows) < len(definition.index_codes):
            exceptions.append(
                self._exception_builder.source_empty(
                    message="some configured indices are missing",
                    missing_count=len(definition.index_codes) - len(snapshot_rows),
                )
            )

        rows = self._build_rows(
            index_codes=definition.index_codes,
            index_names=index_names,
            snapshot_rows=snapshot_rows,
        )
        response = MajorIndicesResponseDto(
            tradingDay=TradingDayDto(
                tradeDate=trading_day_context.expected_trade_date,
                prevTradeDate=trading_day_context.prev_trade_date,
                market="CN_A",
                isTradingDay=trading_day_context.is_trading_day,
                sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
                timezone="Asia/Shanghai",
            ),
            pageStatus=status_result.page_status,
            majorIndices=MajorIndicesPayloadDto(
                definition=MajorIndicesDefinitionDto(
                    definitionKey=definition.definition_key,
                    version=definition.version,
                    fixedCount=10,
                ),
                rows=rows,
            ),
            debugInfo=(
                MajorIndicesDebugInfoDto(
                    modules=[status_result.module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )
        return response

    def _load_definition(self, *, market: str) -> MajorIndicesDefinition:
        payload = self._config_service.get_payload(module_key="majorIndices", market=market)
        version = self._config_service.get_version(module_key="majorIndices", market=market)
        if not isinstance(payload, MajorIndicesStrategyPayload):
            raise StrategyConfigValidationError("majorIndices payload model mismatch")
        return MajorIndicesDefinition(
            definition_key=_DEFAULT_DEFINITION_KEY,
            version=version,
            index_codes=tuple(payload.index_codes),
        )

    def _build_rows(
        self,
        *,
        index_codes: tuple[str, ...],
        index_names: dict[str, str | None],
        snapshot_rows: dict[str, MajorIndicesSnapshotRow],
    ) -> list[MajorIndexRowDto]:
        rows: list[MajorIndexRowDto] = []
        for code in index_codes:
            snapshot = snapshot_rows.get(code)
            if snapshot is None:
                rows.append(
                    MajorIndexRowDto(
                        subject=SubjectRefDto(
                            subjectType="index",
                            subjectCode=code,
                            subjectName=index_names.get(code),
                        ),
                        point=None,
                        change=None,
                        changePct=None,
                        amount=None,
                        direction="UNKNOWN",
                    )
                )
                continue

            change_pct = float(snapshot.pct_chg) if snapshot.pct_chg is not None else None
            rows.append(
                MajorIndexRowDto(
                    subject=SubjectRefDto(
                        subjectType="index",
                        subjectCode=code,
                        subjectName=index_names.get(code),
                    ),
                    point=float(snapshot.close) if snapshot.close is not None else None,
                    change=float(snapshot.change_amount) if snapshot.change_amount is not None else None,
                    changePct=change_pct,
                    amount=float(snapshot.amount) if snapshot.amount is not None else None,
                    direction=self._resolve_direction(change_pct),
                )
            )
        return rows

    @staticmethod
    def _resolve_direction(change_pct: float | None) -> str:
        if change_pct is None:
            return "UNKNOWN"
        if change_pct > 0:
            return "UP"
        if change_pct < 0:
            return "DOWN"
        return "FLAT"

    def _build_error_response(
        self,
        *,
        trading_day_context: MajorIndicesTradingDayContext,
        index_codes: tuple[str, ...],
        debug: bool,
        exceptions: list,
        definition: MajorIndicesDefinition | None = None,
    ) -> MajorIndicesResponseDto:
        fallback_definition = definition or MajorIndicesDefinition(
            definition_key=_DEFAULT_DEFINITION_KEY,
            version="0.0.0",
            index_codes=index_codes,
        )
        rows = self._build_rows(index_codes=fallback_definition.index_codes, index_names={}, snapshot_rows={})
        module_status = ModuleStatusItemDto(
            moduleKey="majorIndices",
            expectedTradeDate=trading_day_context.expected_trade_date,
            observedTradeDate=None,
            lagDays=None,
            status="ERROR",
            note="module failed to load",
        )
        return MajorIndicesResponseDto(
            tradingDay=TradingDayDto(
                tradeDate=trading_day_context.expected_trade_date,
                prevTradeDate=trading_day_context.prev_trade_date,
                market="CN_A",
                isTradingDay=trading_day_context.is_trading_day,
                sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
                timezone="Asia/Shanghai",
            ),
            pageStatus=PageStatusDto(status="ERROR", displayText="模块加载失败", asOfTime=trading_day_context.as_of_time),
            majorIndices=MajorIndicesPayloadDto(
                definition=MajorIndicesDefinitionDto(
                    definitionKey=fallback_definition.definition_key,
                    version=fallback_definition.version,
                    fixedCount=10,
                ),
                rows=rows,
            ),
            debugInfo=(
                MajorIndicesDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

