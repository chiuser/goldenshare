"""Module-local HTTP errors. Never expose exception text or infer save failure."""
import re
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from src.biz.schemas.wealth.market.trading_assistant.errors import TradingAssistantErrorDto, FieldErrorDto
from src.biz.services.wealth.market.trading_assistant.transaction_boundary import CommitOutcomeUnknown
from src.biz.services.wealth.market.trading_assistant.validation import InvalidLedger
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from src.biz.services.wealth.market.trading_assistant.market_facts import SecurityNotEligible, MarketFactsUnavailable


def validation_fields(error):
    allowed = {"name", "brokerName", "initialCash", "initialPositions", "commissionRateWan", "minimumCommission",
        "stampTaxRatePct", "tsCode", "direction", "tradeDate", "occurredOn", "price", "quantity", "amount", "note",
        "availableQuantity", "costPrice", "expectedRevision", "expectedFeeVersionId"}
    rows = error.body.get("initialPositions") if isinstance(error.body, dict) else None
    row_ids = [row.get("clientRowId") if isinstance(row, dict) else None for row in rows] if isinstance(rows, list) else []
    valid_ids = all(type(value) is str and bool(value) for value in row_ids) and len(set(row_ids)) == len(row_ids)
    fields = []
    for issue in error.errors():
        path = issue["loc"][1:]
        names = [part for part in path if isinstance(part, str)]
        if not names or any(name not in allowed for name in names):
            continue
        row_id = None
        if names[0] == "initialPositions" and len(path) > 1 and type(path[1]) is int:
            if not valid_ids or not 0 <= path[1] < len(row_ids):
                names = ["initialPositions"]
            else:
                row_id = row_ids[path[1]]
        fields.append(FieldErrorDto(field=".".join(names), clientRowId=row_id,
            message="请检查必填项、格式和取值范围", affectedOn=None))
    return fields


HTTP_CODES = {"TA_REQUEST_INVALID":400, "TA_REQUEST_ID_CONFLICT":409, "TA_SCOPE_WRITE_PENDING":409,
    "TA_RECOVERY_UNAVAILABLE":404, "TA_RECOVERY_STATE_CHANGED":409, "TA_RECOVERY_QUERY_FAILED":500,
    "TA_WRITE_OUTCOME_UNKNOWN":503, "TA_WRITE_FAILED":500, "TA_ACCOUNT_NOT_FOUND":404,
    "TA_FEE_VERSION_CONFLICT":409, "TA_OBJECT_NOT_FOUND":404, "TA_STATE_CONFLICT":409,
    "TA_READ_CONTEXT_CHANGED":409, "TA_QUERY_FAILED":500}


def error_response(code, message, *, state=None, fields=()):
    data = TradingAssistantErrorDto(code=code, message=message,
        requestId=str(state.request_id) if state else None, attemptId=str(state.attempt_id) if state else None,
        stateVersion=str(state.state_version) if state else None, fieldErrors=list(fields), recovery=None)
    return JSONResponse(data.model_dump(mode="json"), status_code=HTTP_CODES[code])


def command_response(state):
    if state.status == "SAVED":
        first_create = state.accepted_now and state.operation in {"ACCOUNT_CREATE", "TRADE_CREATE", "CASH_FLOW_CREATE"}
        return JSONResponse(state.receipt, status_code=201 if first_create else 200)
    if state.status == "NOT_SAVED":
        return error_response(state.rejection["code"], state.rejection["message"], state=state, fields=state.field_errors)
    return error_response("TA_WRITE_OUTCOME_UNKNOWN", "保存结果正在核对，请勿重复提交", state=state)


class TradingAssistantRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        query_fields = {field.alias for field in self.dependant.query_params}
        async def dispatch(request):
            try:
                keys = [key for key, _ in request.query_params.multi_items()]
                if (len(keys) != len(set(keys)) or any(key not in query_fields for key in keys)
                        or ("limit" in keys and not re.fullmatch(r"[1-9][0-9]*", request.query_params["limit"]))):
                    return error_response("TA_REQUEST_INVALID", "查询参数不符合要求，请检查")
                return await original(request)
            except RequestValidationError as error:
                # Invalid bodies are not trusted for request/row identities or echoed values.
                return error_response("TA_REQUEST_INVALID", "填写内容不符合要求，请检查", fields=validation_fields(error))
            except ResponseValidationError:
                return error_response("TA_QUERY_FAILED", "读取结果不完整，请重试")
            except SecurityNotEligible:
                return error_response("TA_REQUEST_INVALID", "请选择有效的 A 股股票", fields=(FieldErrorDto(
                    field="tsCode", clientRowId=None, message="请选择有效的 A 股股票", affectedOn=None),))
            except WriteProtocolConflict as error:
                return error_response(error.code, "记录或状态不可用，请重新核对")
            except InvalidLedger as error:
                return error_response("TA_REQUEST_INVALID", error.message, fields=(FieldErrorDto(
                    field=error.field, clientRowId=None, message=error.message, affectedOn=error.occurred_on.isoformat()),))
            except CommitOutcomeUnknown:
                if request.url.path.endswith("preview"):
                    return error_response("TA_QUERY_FAILED", "预览未完成，请重新核对")
                return error_response("TA_WRITE_OUTCOME_UNKNOWN", "保存结果尚未确认，请核对原操作")
            except TimeoutError:
                is_write = request.method in {"POST", "PUT"} and not request.url.path.endswith("preview")
                return error_response("TA_WRITE_OUTCOME_UNKNOWN" if is_write else "TA_QUERY_FAILED",
                    "本次处理未完成，请核对原操作" if is_write else "读取未完成，请重试")
            except (SQLAlchemyError, ValidationError, MarketFactsUnavailable):
                is_write = request.method in {"POST", "PUT"} and not request.url.path.endswith("preview")
                is_recovery = "/write-requests/" in request.url.path
                code = ("TA_WRITE_OUTCOME_UNKNOWN" if is_write else
                        "TA_RECOVERY_QUERY_FAILED" if is_recovery else "TA_QUERY_FAILED")
                return error_response(code, "本次处理未完成，请核对原操作" if is_write else "读取未完成，请重试")
        async def handle(request):
            response = await dispatch(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        return handle
