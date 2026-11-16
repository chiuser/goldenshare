"""Adapt the existing probe to Prod's stock adjusted period-bar readiness."""

from sqlalchemy import select

from src.foundation.dao.stock_period_adj_delivery_dao import StockPeriodAdjDeliveryDAO
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.datasets.stock_period_adj_contracts import frequency
from src.foundation.ingestion.stock_period_adj_inputs import factor_changes, open_days
from src.foundation.ingestion.stock_period_adj_readiness import check_current_period
from src.ops.models.ops.task_run import TaskRun

CURRENT_CONDITION = 'stock_period_adj_current_ready'
HISTORY_CONDITION = 'stock_period_adj_factor_history_ready'
PROBE_WINDOW = ('20:00', '00:00')
PROBE_INTERVAL_SECONDS = 60
PROBE_TIMEZONE = 'Asia/Shanghai'
MAX_TRIGGERS_PER_DAY = 1


def validate_rule(rule):
    definition = get_dataset_definition(rule.dataset_key)
    if definition.planning.stock_period_adj_policy is None:
        raise ValueError('股票复权周期线探针只适用于声明该能力的数据集')
    if (rule.probe_condition_json or {}).get('type') not in {CURRENT_CONDITION, HISTORY_CONDITION}:
        raise ValueError('股票复权周期线探针条件不受支持')
    if rule.source_key != definition.source.source_key_default:
        raise ValueError('股票复权周期线探针必须使用定义中的源')
    action = rule.on_success_action_json or {}
    request = action.get('request') or {}
    if action.get('action_type') != 'dataset_action' or action.get('action_key') != definition.action_key('maintain'):
        raise ValueError('股票复权周期线探针动作与数据集不匹配')
    if request.get('time_input') != {'mode': 'point'} or request.get('filters') or request.get('maintenance_intent'):
        raise ValueError('自动当期任务禁止固定日期、股票过滤或自填用途')
    if (rule.window_start, rule.window_end) != PROBE_WINDOW or rule.probe_interval_seconds != PROBE_INTERVAL_SECONDS or rule.timezone_name != PROBE_TIMEZONE or rule.max_triggers_per_day != MAX_TRIGGERS_PER_DAY:
        raise ValueError('股票复权周期线探针必须使用20:00至次日00:00及60秒固定配置')
    return definition


def active_task(session, dataset_key, business_date, purpose='current_period'):
    return session.scalar(select(TaskRun.id).where(TaskRun.resource_key == dataset_key,
        TaskRun.action == 'maintain', TaskRun.status.in_(['queued','running','canceling']),
        TaskRun.time_input_json['business_date'].as_string() == business_date.isoformat(),
        TaskRun.request_payload_json['maintenance_intent']['kind'].as_string() == purpose).limit(1))


def evaluate(session, rule, *, current):
    definition = validate_rule(rule)
    from zoneinfo import ZoneInfo
    local = current.astimezone(ZoneInfo(PROBE_TIMEZONE))
    day = local.date()
    payload = {'business_date': day.isoformat()}
    if local.strftime('%H:%M') < PROBE_WINDOW[0] or not open_days(session, day, day):
        return False, '未到当天交易日20:00探测窗口', payload
    if rule.probe_condition_json['type'] == HISTORY_CONDITION:
        dao = StockPeriodAdjDeliveryDAO(session)
        frozen = dao.frozen_intent(f'factor_history:{frequency(definition)}:{day.isoformat()}')
        if frozen and dao.get(frozen.batch_id, 'batch_closed', 'batch_closed'):
            return False, '本频当天历史回刷已完成', payload
        if active_task(session, definition.dataset_key, day, 'factor_history'):
            return False, '本频当天已有活动历史任务', payload
        if frozen:
            return True, '按首次保存的本频历史计划入队', {**payload, 'batch_id':str(frozen.batch_id)}
        if not all(dao.complete(day, freq) for freq in ('week','month')):
            return False, '等待同业务日两频当期业务交付完成', payload
        changes = factor_changes(session, day)
        payload.update({key:value for key,value in changes.items() if key != 'changed_codes'})
        return (True, '复权因子变化，触发本频历史回刷', payload) if changes['changed_count'] else (False, '本次复权因子检查完成，变化股票为0', payload)
    if StockPeriodAdjDeliveryDAO(session).complete(day, frequency(definition)):
        return False, '本频当天当期业务交付已完成', payload
    if active_task(session, definition.dataset_key, day):
        return False, '本频当天已有活动任务', payload
    return check_current_period(session, dataset_key=definition.dataset_key, business_date=day)
