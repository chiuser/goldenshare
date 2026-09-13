"""Reconstruct balances independently of Account methods; reject fabricated totals."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal as D, ROUND_HALF_UP


def require(condition, message):
    if not condition:
        raise ValueError('account audit: '+message)


def audit(result):
    """Internal arithmetic/lot audit, NOT certification of source prices or signals."""
    spec = result['spec']
    cash, shares, rights, basis, realized = spec['initial_cash'], 0, D(0), D(0), D(0)
    lots, seen_fills, marks, entitlements = defaultdict(int), set(), [], {}
    last_time = ''
    for row in result['journal']:
        time = row['time']
        require(time >= last_time, 'journal chronology')
        last_time = time
        expected_cash, expected_shares, expected_rights = D(0), 0, D(0)
        if row['kind'] == 'fill':
            index = row['fill_index']
            require(index not in seen_fills and index == len(seen_fills), 'duplicate/out-of-order fill')
            seen_fills.add(index)
            fill = result['fills'][index]
            qty, price, rule = fill['quantity'], fill['price'], fill['rule']
            day = datetime.fromisoformat(time).date()
            buy = fill['side'] == 'buy'
            require(fill['side'] in ('buy', 'sell') and type(qty) is int and qty > 0 and price > 0,
                    'invalid fill')
            require(fill['time'] == time and time < fill['bar_end'], 'fill timestamp')
            require(rule['start'] <= day <= rule['end'], 'historical rule date')
            require(qty <= int(D(fill['previous_volume'])*spec['participation']), 'participation')
            minimum, step = ((rule['buy_min'], rule['buy_step']) if buy else
                             (rule['sell_min'], rule['sell_step']))
            legal_odd = not buy and rule['odd_final_sell'] and qty == shares
            require(legal_odd or qty >= minimum and (qty-minimum) % step == 0, 'lot rule')
            weights = ({'B1': D('.2'), 'B2': D('.3'), 'B3': D('.5')} if buy else
                       {'S1': D('.5'), 'S2': D('.3'), 'S3': D('.2')})
            require(set(fill['active']) <= weights.keys(), 'active classes')
            used, base = (fill['bought'], fill['q']) if buy else (fill['sold'], fill['v'])
            require(used <= int(base*sum((weights[g] for g in fill['active']), D(0))), 'share quota')
            amount = price*qty
            def rounded(value):
                return value.quantize(D('.01'), rounding=ROUND_HALF_UP)
            costs = dict(commission=rounded(max(spec['minimum_commission'], amount*spec['commission_rate'])),
                         transfer=rounded(amount*rule['transfer_rate']),
                         stamp=rounded(D(0) if buy else amount*rule['stamp_sell_rate']))
            require(costs == fill['fees'], 'fees')
            expected_cash = (-amount if buy else amount)-sum(costs.values())
            expected_shares = qty if buy else -qty
            require(fill['cash_delta'] == expected_cash, 'fill cash delta')
            if buy:
                basis -= expected_cash
                lots[day] += qty
                pnl = D(0)
            else:
                require(qty <= sum(n for d, n in lots.items() if d < day), 'T+1 oversell')
                allocated = basis if qty == shares else basis*qty/shares
                pnl = expected_cash-allocated
                realized += pnl
                basis -= allocated
                remaining = qty
                for bought_day in sorted(lots):
                    if bought_day < day:
                        count = min(remaining, lots[bought_day])
                        lots[bought_day] -= count
                        remaining -= count
            require(fill['realized_profit'] == pnl and fill['cost_basis'] == basis, 'average cost/PnL')
            require(fill['cash'] == cash+expected_cash and fill['shares'] == shares+expected_shares,
                    'fill balances')
        elif row['kind'] == 'unit_split':
            factor = row['effect']['value']
            require(factor > 0 and shares*factor == int(shares*factor), 'split quantity')
            expected_shares = int(shares*factor)-shares
            for day in lots:
                require(lots[day]*factor == int(lots[day]*factor), 'split lot')
                lots[day] = int(lots[day]*factor)
        elif row['kind'] == 'cash_right':
            ref, value = row['effect']['reference'], row['effect']['value']
            require(ref not in entitlements and value > 0, 'duplicate cash right')
            entitlements[ref] = value
            expected_rights = value
            realized += value
        elif row['kind'] == 'cash_pay':
            ref, value = row['effect']['reference'], row['effect']['value']
            require(entitlements.get(ref) == value and value > 0, 'payment entitlement')
            entitlements[ref] = D(0)
            expected_cash, expected_rights = value, -value
        elif row['kind'] == 'mark':
            value = cash+shares*row['price']+rights
            require(row['equity'] == value, 'equity mark')
            require(abs(value-(spec['initial_cash']+realized+shares*row['price']-basis)) < D('.000001'),
                    'equity/PnL reconciliation')
            marks.append((time, value, basis, realized, cash, shares, rights, row['price']))
        else:
            raise ValueError('account audit: unknown journal entry')
        require((row['cash_delta'], row['share_delta'], row['right_delta']) ==
                (expected_cash, expected_shares, expected_rights), 'journal delta')
        cash += expected_cash
        shares += expected_shares
        rights += expected_rights
        require(cash >= 0 and shares >= 0 and rights >= 0, 'negative balance')
        require((cash, shares, rights) == (row['cash'], row['shares'], row['rights']), 'journal balances')
        require(shares == sum(lots.values()), 'lot conservation')
    require(len(seen_fills) == len(result['fills']), 'unposted fills')
    require(marks == [(r['time'], r['equity'], r['cost_basis'], r['realized'], r['cash'],
                       r['shares'], r['rights'], r['price']) for r in result['equity']],
            'equity table differs from journal')
    end = result['end_state']
    require((cash, shares, rights) == (end['cash'], end['shares'], end['rights']), 'end balances')
    cycle_ids = [cycle['cycle'] for cycle in result['cycles']]
    require(cycle_ids == sorted(set(cycle_ids)), 'duplicate/out-of-order completed cycles')
    for cycle in result['cycles']:
        fills = [f for f in result['fills'] if f['cycle'] == cycle['cycle']]
        require(fills and fills[0]['side'] == 'buy' and fills[-1]['side'] == 'sell'
                and fills[-1]['shares'] == 0, 'cycle must have opened and fully sold')
        flows = [r['cash_delta'] for r in result['journal'] if r['cycle'] == cycle['cycle']]
        require(cycle['profit'] == cycle['end_cash']-cycle['start_cash'], 'cycle cash PnL')
        require(sum(flows, D(0)) == cycle['profit'], 'cycle fill and entitlement cash PnL')
    return dict(status='passed', fills=len(seen_fills), marks=len(marks),
                cash=cash, shares=shares, rights=rights,
                scope='internal_arithmetic_not_source_or_signal_certification')


def metrics(result):
    audit(result)
    initial = result['spec']['initial_cash']
    curve = result['equity']
    ending = curve[-1]['equity'] if curve else initial
    peak, drawdown = initial, D(0)
    for row in curve:
        peak = max(peak, row['equity'])
        drawdown = max(drawdown, 1-row['equity']/peak)
    profits = [c['profit'] for c in result['cycles']]
    winners, losers = [v for v in profits if v > 0], [-v for v in profits if v < 0]
    actual_days = {r['time'][:10] for r in curve}
    exposed_days = {r['time'][:10] for r in curve if r['shares'] > 0}
    exposed_days |= {f['time'][:10] for f in result['fills']}  # Include a final morning exit.
    return dict(initial_cash=initial, ending_equity=ending, total_return=ending/initial-1,
                maximum_drawdown=drawdown, completed_cycles=len(profits),
                win_rate=D(len(winners))/len(profits) if profits else None,
                profit_loss_ratio=(sum(winners)/len(winners))/(sum(losers)/len(losers))
                    if winners and losers else None,
                exposure_days=len(exposed_days), actual_days=len(actual_days),
                end_shares=result['end_state']['shares'], end_rights=result['end_state']['rights'],
                unfinished_cycle=result['end_state']['phase'] != 'flat')
