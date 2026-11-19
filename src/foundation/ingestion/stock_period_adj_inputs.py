"""Read existing Prod business inputs; zero rows are a completed zero result."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select

from src.foundation.clients.reference_data import local_reference_data
from src.foundation.dao.trade_calendar_dao import TradeCalendarDAO
from src.foundation.datasets.stock_period_adj_contracts import StockPeriodAdjContractError, digest, period_start
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving_light.bse_mapping import BseMappingLight
from src.foundation.models.raw.raw_stock_basic import RawStockBasic
from src.foundation.models.raw.raw_suspend_d import RawSuspendD
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor


def today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()


def open_days(session, start, end):
    return TradeCalendarDAO(session).get_open_dates('SSE', start, end)


def confirmed_history_codes(session, codes):
    """Resolve only requested identities, including delisted stocks' history."""
    if not codes:
        return {}
    mappings = {}
    for old, new in session.execute(select(BseMappingLight.o_code, BseMappingLight.n_code).where(
            or_(BseMappingLight.o_code.in_(codes), BseMappingLight.n_code.in_(codes)))):
        if old in mappings and mappings[old] != new:
            raise StockPeriodAdjContractError(f'{old}存在多个确认股票代码', 'input_changed')
        mappings[old] = new
    identities = set(codes) | set(mappings) | set(mappings.values())
    master = set(session.scalars(select(RawStockBasic.ts_code).where(
        RawStockBasic.curr_type == 'CNY', RawStockBasic.ts_code.in_(identities))))
    confirmed = master | {new for old, new in mappings.items() if old in master}
    return {code: mappings.get(code, code) for code in codes if mappings.get(code, code) in confirmed}


def factor_changes(session, day, *, check=lambda: None):
    """Compare adjacent open dates; zero business rows mean a zero result."""
    check()
    if not open_days(session, day, day):
        raise StockPeriodAdjContractError(f'{day}不是已有日历中的开市日', 'input_not_ready')
    reference = local_reference_data(session)
    if reference is not None:
        rows = reference.calendar.recent_open_rows(
            exchange="SSE", bound=day, limit=1, include_bound=False,
        )
        previous = rows[0].trade_date if rows else None
    else:
        previous = session.scalar(select(func.max(TradeCalendar.trade_date)).where(
            TradeCalendar.exchange == 'SSE', TradeCalendar.is_open.is_(True), TradeCalendar.trade_date < day))
    rows = session.execute(select(EquityAdjFactor.trade_date, EquityAdjFactor.ts_code, EquityAdjFactor.adj_factor)
        .where(EquityAdjFactor.trade_date.in_([previous, day]))
        .order_by(EquityAdjFactor.trade_date, EquityAdjFactor.ts_code)).all()
    check()
    before = {code: value for stamp, code, value in rows if stamp == previous}
    after = {code: value for stamp, code, value in rows if stamp == day}
    comparable = sorted(before.keys() & after.keys())
    identities = confirmed_history_codes(session, comparable)
    check()
    changed = set()
    compared = 0
    for code in comparable:
        if code not in identities:
            continue
        if before[code] is None or after[code] is None or before[code] <= 0 or after[code] <= 0:
            raise StockPeriodAdjContractError(f'{code}相邻交易日复权因子无效', 'input_changed')
        compared += 1
        if before[code] != after[code]:
            changed.add(identities[code])
    check()
    return {'business_date': day.isoformat(), 'previous_business_date': previous.isoformat() if previous else None,
        'factor_rows_previous': len(before), 'factor_rows_current': len(after), 'compared_stocks': compared,
        'changed_codes': sorted(changed), 'changed_count': len(changed),
        'input_digest': digest({'factors': [tuple(row) for row in rows], 'identities': identities})}


def period_inputs(session, *, day, freq, selected_code=None, closed_period=False):
    """Freeze admitted codes and each mandatory code's last required source day."""
    days = open_days(session, period_start(day, freq), day)
    if not days or days[-1] != day:
        raise StockPeriodAdjContractError(f'{day}不是已有日历中的开市日', 'input_not_ready')
    mappings = {}
    for old_code, new_code in session.execute(select(BseMappingLight.o_code, BseMappingLight.n_code)):
        if old_code in mappings and mappings[old_code] != new_code:
            raise StockPeriodAdjContractError(f'{old_code}存在多个确认股票代码', 'input_changed')
        mappings[old_code] = new_code
    master = list(session.scalars(select(RawStockBasic).where(RawStockBasic.curr_type == 'CNY',
        RawStockBasic.list_date <= day,
        (RawStockBasic.delist_date.is_(None) | (RawStockBasic.delist_date > (days[0] if closed_period else day))))))
    by_original = {row.ts_code: row for row in master}
    admitted = {}
    for row in master:
        code = mappings.get(row.ts_code, row.ts_code)
        if code != row.ts_code and code in by_original:
            continue
        if selected_code and code != selected_code:
            continue
        admitted[code] = (row.list_date, row.delist_date)
    if selected_code and selected_code not in admitted:
        raise StockPeriodAdjContractError(f'{selected_code}不在确认的人民币股票范围', 'source_scope_invalid')
    suspensions = session.execute(select(RawSuspendD.ts_code, RawSuspendD.trade_date,
        RawSuspendD.suspend_type, RawSuspendD.suspend_timing).where(RawSuspendD.trade_date.in_(days))).all()
    full_day = {(mappings.get(row.ts_code, row.ts_code), row.trade_date) for row in suspensions
                if row.suspend_type == 'S' and not row.suspend_timing}
    required = {}
    for code, (listed, delisted) in admitted.items():
        needed = [candidate for candidate in days if candidate >= listed and (delisted is None or candidate < delisted) and (code, candidate) not in full_day]
        if needed:
            # A full-day suspension on D may legitimately be absent altogether.
            if closed_period or (code, day) not in full_day:
                required[code] = needed[-1].isoformat()
    payload = {'eligible_codes': sorted(admitted), 'required_dates': required,
               'full_day_suspended': sorted(code for code in admitted if (code, day) in full_day),
               'input_digest': digest({'days': days, 'stocks': admitted, 'full_day': sorted(full_day), 'mapping': mappings})}
    return payload
