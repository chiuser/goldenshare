"""Prod stock adjusted period bars: source values, budgets and cycle identity."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from uuid import UUID


SOURCE_FIELDS = (
    'ts_code', 'trade_date', 'end_date', 'freq', 'open', 'high', 'low',
    'close', 'pre_close', 'open_qfq', 'high_qfq', 'low_qfq', 'close_qfq',
    'open_hfq', 'high_hfq', 'low_hfq', 'close_hfq', 'vol', 'amount', 'change', 'pct_chg',
)
READINESS_FIELDS = ('ts_code', 'trade_date', 'end_date')
BUSINESS_FIELDS = SOURCE_FIELDS[4:]
ROW_BLOCK_SIZE = 128


class StockPeriodAdjContractError(ValueError):
    def __init__(self, message, code='source_schema_invalid'):
        super().__init__(message)
        self.code = code if code.startswith('stock_period_adj.') else f'stock_period_adj.{code}'


@dataclass(frozen=True, slots=True)
class StockPeriodAdjExecutionPolicy:
    contract_version: int = 1
    page_limit: int = 6000
    max_pages: int = 3
    max_rows_per_unit: int = 12000
    max_units: int = 1000
    max_payload_bytes: int = 8 * 1024 * 1024
    max_plan_bytes: int = 1024 * 1024
    source_timeout_seconds: int = 20
    db_statement_timeout_seconds: int = 20
    lock_timeout_seconds: int = 2
    cancel_poll_seconds: int = 2
    progress_interval_seconds: int = 5
    observation_timeout_seconds: int = 2

    @property
    def maintenance_intents(self):
        return ('period', 'current_period')


def json_value(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f') if value else '0'
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(type(value).__name__)


def canonical_json(value):
    return json.dumps(value, default=json_value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def check_size(value, maximum, code='row_budget_exceeded'):
    if len(canonical_json(value).encode()) > maximum:
        raise StockPeriodAdjContractError('载荷超过已声明字节限制', code)


def parse_day(value):
    if type(value) is date:
        return value
    try:
        if isinstance(value, str) and re.fullmatch(r'\d{8}', value):
            return datetime.strptime(value, '%Y%m%d').date()
        if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value)
    except ValueError:
        pass
    raise StockPeriodAdjContractError(f'行情业务日期无效：{value!r}')


def period_start(day, freq):
    return day - timedelta(days=day.weekday()) if freq == 'week' else day.replace(day=1)


def period_date(day, freq):
    return period_start(day, freq) + timedelta(days=4) if freq == 'week' else day.replace(day=monthrange(day.year, day.month)[1])


def frequency(definition):
    return definition.storage.row_identity_filters['freq']


def definition_issues(definition):
    policy = definition.planning.stock_period_adj_policy
    if policy is None:
        return []
    valid = (
        definition.dataset_key in {'stk_period_bar_adj_week', 'stk_period_bar_adj_month'}
        and definition.source.api_name == 'stk_week_month_adj'
        and definition.source.source_fields == SOURCE_FIELDS
        and definition.source.source_key_default == 'tushare'
        and definition.storage.row_identity_filters == {'freq': definition.dataset_key.rsplit('_', 1)[1]}
        and definition.storage.delivery_table == 'core.stock_period_adj_delivery'
        and definition.storage.delivery_dao_name == 'stock_period_adj_delivery'
        and definition.storage.raw_table == 'raw_tushare.stk_period_bar_adj'
        and definition.storage.target_table == 'core_serving.stk_period_bar_adj'
        and definition.storage.conflict_columns == definition.storage.raw_conflict_columns == ('ts_code', 'trade_date', 'freq')
        and definition.storage.write_path == 'raw_core_upsert_with_period_delivery'
        and definition.planning.weekly_adj_policy is None
        and definition.planning.unit_builder_key == 'stock_period_adj'
        and definition.planning.page_limit == policy.page_limit
        and definition.planning.max_source_rows_per_unit == policy.max_rows_per_unit
        and definition.planning.max_units_per_execution == policy.max_units
        and definition.planning.fetch_concurrency == 1
        and definition.transaction.commit_policy == 'unit'
        and definition.transaction.idempotent_write_required
        and definition.quality.reject_policy == 'fail_unit_on_any_rejection'
    )
    return [] if valid else [('stock_period_adj_binding_invalid', '股票复权周/月线具名合同绑定不完整')]


def normalize_rows(rows, *, freq, policy, readiness=False):
    """Validate real source fields before admission; retain Decimal and source dates."""
    fields = READINESS_FIELDS if readiness else SOURCE_FIELDS
    if len(rows) > policy.max_rows_per_unit:
        raise StockPeriodAdjContractError('源单元行数超限', 'row_budget_exceeded')
    result = []
    keys = {}
    for source in rows:
        if set(source) != set(fields):
            raise StockPeriodAdjContractError('源列必须与本次三列/21列合同完整一致')
        row = dict(source)
        if not isinstance(row['ts_code'], str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', row['ts_code']):
            raise StockPeriodAdjContractError('源股票代码无效')
        row['trade_date'], row['end_date'] = parse_day(row['trade_date']), parse_day(row['end_date'])
        if not readiness:
            if row['freq'] != freq:
                raise StockPeriodAdjContractError('源频率与数据集不一致', 'source_scope_invalid')
            for field in BUSINESS_FIELDS:
                value = row[field]
                if value is None:
                    continue
                if isinstance(value, (float, bool)):
                    raise StockPeriodAdjContractError(f'{field}未经Decimal解码')
                try:
                    number = Decimal(value)
                    precision = 20 if field in {'vol', 'amount'} else 10 if field == 'pct_chg' else 18
                    if not number.is_finite() or abs(number) >= Decimal(10) ** (precision - 4) or number.quantize(Decimal('.0001')) != number:
                        raise InvalidOperation
                except (InvalidOperation, ValueError, TypeError):
                    raise StockPeriodAdjContractError(f'{field}超过目标数值精度') from None
                row[field] = number
        key = (row['ts_code'], row['trade_date'])
        if key in keys and row != keys[key]:
            raise StockPeriodAdjContractError(f'{key}同次源捕获出现异值', 'source_key_conflict')
        keys[key] = row
        result.append(row)
    check_size(result, policy.max_payload_bytes)
    return result


def validate_response(response, *, freq, readiness=False):
    fields = READINESS_FIELDS if readiness else SOURCE_FIELDS
    try:
        data = response['data']
        actual = data['fields']
        items = data['items']
        if len(actual) != len(fields) or set(actual) != set(fields) or not isinstance(items, list):
            raise StockPeriodAdjContractError('源响应缺列、重复列或多余列')
        rows = []
        for item in items:
            if len(item) != len(actual):
                raise StockPeriodAdjContractError('源响应列宽错误')
            rows.append(dict(zip(actual, item)))
    except (KeyError, TypeError):
        raise StockPeriodAdjContractError('源响应结构错误') from None
    return normalize_rows(rows, freq=freq, policy=StockPeriodAdjExecutionPolicy(), readiness=readiness)


def select_serving(rows, freq):
    """Select one whole latest source row per stock and natural period."""
    groups = {}
    for row in rows:
        key = row['ts_code'], period_start(row['trade_date'], freq)
        groups.setdefault(key, []).append(row)
    selected = []
    for key, group in sorted(groups.items()):
        valid = [row for row in group if row['end_date'] is not None]
        if not valid:
            raise StockPeriodAdjContractError(f'{key}没有有效计算截至日期', 'latest_version_conflict')
        latest = max(row['end_date'] for row in valid)
        winners = [row for row in valid if row['end_date'] == latest]
        values = [tuple(row[field] for field in BUSINESS_FIELDS) for row in winners]
        if any(value != values[0] for value in values[1:]):
            raise StockPeriodAdjContractError(f'{key}最新计算截至日期出现不同业务值', 'latest_version_conflict')
        selected.append(max(winners, key=lambda row: (row['trade_date'], row['ts_code'])))
    return selected
