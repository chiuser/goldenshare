"""Causal near-term text selection over complete, immutable forecast facts."""
from bisect import bisect_right
import math
from .forecast_math import Interval, as_interval, intersect, number_inside


from .forecast_spec import FORECAST_SPEC


def reference_band(bars, period, through, endpoint, span, clocks, check, spec=FORECAST_SPEC):
    check()
    count = bisect_right([b.time for b in bars], through)
    prefix = bars[:count]
    base = dict(through=through, endpoint=endpoint, barsAhead=span, samples=0, reason='INSUFFICIENT_SAMPLES')
    if not prefix or prefix[-1].time != through or not endpoint or span < 1:
        return dict(base, reason='ENDPOINT_MISMATCH')
    current = prefix[-1].close
    target_clock = '15:00' if period == 'day' else endpoint[11:16]
    if period != 'day' and (target_clock not in clocks or through[11:16] not in clocks or
                           clocks[(clocks.index(through[11:16]) + span) % len(clocks)] != target_clock):
        return dict(base, reason='ENDPOINT_MISMATCH')
    if not math.isfinite(current) or current <= 0:
        return dict(base, reason='INVALID_PRICE')
    moves = []
    for i in range(count - 1, span - 1, -1):
        if (count - i) % 1000 == 0:
            check()
        bar = prefix[i]
        if period != 'day' and bar.time[11:16] != target_clock:
            continue
        old = prefix[i - span]
        if not all(math.isfinite(b.close) and b.close > 0 for b in (bar, old)):
            return dict(base, reason='INVALID_PRICE')
        if period != 'day' and old.time[11:16] != clocks[(clocks.index(target_clock) - span) % len(clocks)]:
            return dict(base, reason='ENDPOINT_MISMATCH')
        moves.append(abs(bar.close / old.close - 1))
        if len(moves) == spec.display_move_samples:
            break
    check()
    if len(moves) < spec.display_move_samples:
        return dict(base, samples=len(moves))
    rank = math.ceil(spec.display_move_quantile * len(moves))
    q = sorted(moves)[rank - 1]
    low = max(0., current * (1-q))
    return dict(base, reason=None, samples=len(moves), rank=rank, q=q, currentClose=current,
                priceRange=Interval(low, current * (1+q), low > 0, True).json())


def build_display_context(bars, period, through, result, clocks, check=lambda: None, spec=FORECAST_SPEC):
    context = dict(entry=None, target=None)
    activation = result.get('activation')
    if activation and activation['ranges']:
        context['entry'] = reference_band(bars, period, through, activation['endpoint'], 1, clocks, check, spec)
    if result.get('targetEndpoint') and result['status'] in ('READY','CONDITIONAL_ENTRY'):
        context['target'] = reference_band(bars, period, through, result['targetEndpoint'], result['barsAhead'], clocks, check, spec)
    return context


def time_text(value, period):
    if value is None:
        return '--'
    return value[5:10].replace('-','/') + (' 收盘' if period == 'day' else ' '+value[11:16]+' 收盘')


def shown_interval(interval, places):
    lo = number_inside(interval.lo, True, places)
    hi = None if interval.hi is None else number_inside(interval.hi, False, places)
    if hi is not None and lo > hi:
        return None
    return lo, hi, places


def price_text(interval, places=None, omit_low=False, omit_high=False):
    places = places or (FORECAST_SPEC.price_boundary_places,)
    shown = next((x for p in places if (x := shown_interval(interval, p)) is not None), None)
    if shown is None:
        return None
    lo, hi, p = shown
    if omit_high or hi is None:
        return f'不低于{lo:.{p}f}点'
    if omit_low or interval.lo == 0:
        return f'不高于{hi:.{p}f}点'
    return f'{lo:.{p}f}～{hi:.{p}f}点'


def _band(value):
    return as_interval(value['priceRange']) if value and value.get('reason') is None else None


def _covers(outer, inner):
    cut = intersect(outer, inner)
    return cut == inner


def select_display(result, context, check=lambda: None, spec=FORECAST_SPEC):
    entry_band, target_band = _band(context.get('entry')), _band(context.get('target'))
    activation = result.get('activation')
    selected = []
    decisions = []
    if activation:
        for group in activation['ranges']:
            check()
            raw = as_interval(group['priceRange'])
            near = intersect(raw, entry_band) if entry_band else None
            decisions.append(dict(kind='activation', id=group['entryRangeId'], kept=near is not None,
                                  reason='NEAR' if near else 'FAR' if entry_band else 'NO_SCALE'))
            if near:
                selected.append(dict(group=group, near=near))
    exclusions = []
    if activation and activation['ranges']:
        for part in activation['exclusions']:
            check()
            reason = part['reason']
            if reason == 'PRECISION_UNRESOLVED':
                continue
            protected = reason in ('PRICE_NOT_EXTREME', 'WRONG_COLOR_OR_ZERO')
            keep = protected or bool(entry_band and intersect(as_interval(part['priceRange']), entry_band))
            decisions.append(dict(kind='exclusion', reason=reason, protected=protected, kept=keep))
            if keep:
                exclusions.append(part)
    commons = []
    for group in result.get('commonConditions', []):
        check()
        domain = as_interval(group['entryDomain']) if group['entryDomain'] else None
        relevant = [x for x in selected if x['group']['entryRangeId'] in group['entryRangeIds']
                    and domain and intersect(x['near'], domain)] if activation else []
        eligible = not activation or bool(relevant)
        universal = not activation or bool(selected) and all(
            x['group']['entryRangeId'] in group['entryRangeIds'] and domain and _covers(domain, as_interval(x['group']['priceRange']))
            for x in selected)
        for close_range in group['closeRanges']:
            raw = as_interval(close_range)
            near = bool(target_band and intersect(raw, target_band))
            text = price_text(raw, (spec.structure_text_places, spec.price_display_places, spec.price_boundary_places))
            kept = eligible and near and text is not None and (universal or price_text(domain) is not None)
            decisions.append(dict(kind='structure', route=group['route'], kept=kept,
                                  reason='NEAR' if kept else 'NO_APPLICABLE_ENTRY' if not eligible else 'FAR' if target_band else 'NO_SCALE'))
            if kept:
                commons.append(dict(group=group, interval=raw, text=text, universal=universal))
    target_exclusions = []
    for part in result.get('targetEntryExclusions', []):
        check()
        if part['reason'] == 'PRECISION_UNRESOLVED':
            continue
        if any(x['group']['entryRangeId'] in part['entryRangeIds'] and intersect(x['near'], as_interval(part['priceRange'])) for x in selected):
            target_exclusions.append(part)
    return dict(selected=selected, exclusions=exclusions, commons=commons, targetExclusions=target_exclusions,
                decisions=decisions, entryBand=entry_band, targetBand=target_band)


def make_display(result, period, through, mode, context, check=lambda: None, spec=FORECAST_SPEC):
    status = result['status']
    direction = '顶部' if result.get('direction') == 'TOP' else '底部'
    side = '顶' if direction == '顶部' else '底'
    labels = dict(READY=f'{side}钝化有效', CONDITIONAL_ENTRY=f'需先形成{side}钝化', ENTRY_ONLY='可算钝化条件',
                  NO_CANDIDATE='暂无条件', CONFIRMED='已确认', PRECISION_PENDING='待核验', DELAYED='数据滞后', EMPTY='暂无数据')
    target, lines = '暂无结构条件', []
    chosen = select_display(result, context, check, spec)
    activation = result.get('activation')
    has_activation = bool(activation and activation['ranges'])
    if has_activation:
        stamp = time_text(activation['endpoint'], period)
        if chosen['entryBand'] is None:
            labels[status] = '待更新'
            lines.append('近期点位暂未生成。')
        elif not chosen['selected']:
            labels[status] = '近期暂无条件'
            lines.append(f'近期触发：暂无近期{side}钝化条件。')
        else:
            for item in chosen['selected']:
                raw = as_interval(item['group']['priceRange'])
                band = chosen['entryBand']
                # Only the outer divergence boundary may be omitted; never join references or precision gaps.
                outer = [p for p in activation['exclusions'] if p['reason'] != 'PRECISION_UNRESOLVED' and
                         (p['priceRange']['upper'] is not None and p['priceRange']['upper'] <= raw.lo if side == '底' else raw.hi is not None and p['priceRange']['lower'] >= raw.hi)]
                nearest = (max(outer, key=lambda p:p['priceRange']['upper']) if side == '底' else min(outer, key=lambda p:p['priceRange']['lower'])) if outer else None
                bounds = [as_interval(g['priceRange']) for g in activation['ranges']]
                is_outer = raw.lo == min(r.lo for r in bounds) if side == '底' else all(r.hi is not None for r in bounds) and raw.hi == max(r.hi for r in bounds)
                divergence = is_outer and nearest is not None and nearest['reason'] == 'DIF_NOT_DIVERGENT'
                omit_low = divergence and side == '底' and raw.lo < band.lo and len(chosen['selected']) == 1
                omit_high = divergence and side == '顶' and raw.hi is not None and raw.hi > band.hi and len(chosen['selected']) == 1
                text = price_text(raw, omit_low=omit_low, omit_high=omit_high)
                if text:
                    lines.append(f'钝化触发：{stamp}{text}，可形成{side}钝化。')
        if chosen['entryBand']:
            for part in chosen['exclusions']:
                text = price_text(as_interval(part['priceRange']))
                if not text:
                    continue
                if part['reason'] == 'WRONG_COLOR_OR_ZERO':
                    lines.append(f'推算失效：{stamp}{text}，MACD柱色改变或出现零柱，需重新判断。')
                else:
                    why = '指标也创新高' if side == '顶' else '指标也创新低'
                    suffix = f'，{why}' if part['reason'] == 'DIF_NOT_DIVERGENT' else ''
                    lines.append(f'未触发：{stamp}{text}{suffix}，{side}钝化条件不成立。')
        target = f'{stamp}后更新结构条件'
    elif status == 'READY':
        lines.append(f'当前{side}钝化有效。')
    if status in ('READY', 'CONDITIONAL_ENTRY'):
        if chosen['commons']:
            target = f'{time_text(result["targetEndpoint"], period)} · {direction}结构条件'
            for item in chosen['commons']:
                if item['universal']:
                    prefix = f'若{side}钝化形成并保持有效' if activation else f'若{side}钝化保持有效'
                else:
                    domain_text = price_text(as_interval(item['group']['entryDomain']))
                    prefix = f'仅当{time_text(activation["endpoint"], period)}在{domain_text}，且{side}钝化有效时'
                lines.append(f'结构成立：{prefix}，最早可在{time_text(result["targetEndpoint"], period)}形成{direction}结构；当前近期适用的收盘区间为{item["text"]}。')
        elif chosen['targetBand'] is None or has_activation and chosen['entryBand'] is None:
            lines.append('暂不提供结构条件。')
        elif not activation or chosen['selected']:
            lines.append(f'结构条件待{time_text(activation["endpoint"], period)}后更新。' if activation else '当前暂无近期结构条件，新收盘后更新。')
        else:
            lines.append(f'当前暂无近期结构条件，{time_text(activation["endpoint"], period)}后更新。')
        for part in chosen['targetExclusions']:
            why = {'CANCEL_BEFORE_TARGET': f'{side}钝化会先消失', 'EARLY_STRUCTURE': '结构会在更早一根形成',
                   'COLOR_OR_ZERO': '中间柱色改变或出现零柱', 'NO_TARGET_SOLUTION': '该时点没有符合条件的结构价格'}[part['reason']]
            lines.append(f'结构不适用：{time_text(activation["endpoint"], period)}在{price_text(as_interval(part["priceRange"]))}，{why}。')
        if result['barsAhead'] > (2 if activation else 1):
            value = '该次钝化收盘价' if activation else f'{result["assumption"]["intermediateCloseExpression"]["constant"]:.2f}点'
            lines.append(f'中间收盘暂按{value}持平；实际走势变化后重算。')
        update = f'{time_text(activation["endpoint"], period)}后更新结构条件和确认时点。' if activation else '新收盘后更新结构条件和确认时点。'
        if chosen['commons']:
            lines.append(update + f'{side}钝化消失或出现零柱时，原条件失效；未达到上述结构区间不等于钝化消失。')
        elif status == 'READY':
            lines.append(update + f'{side}钝化消失或出现零柱时，原条件失效。')
    elif status == 'ENTRY_ONLY':
        lines.append('后续结构时点暂未找到，本周期新收盘后更新。')
    elif status == 'CONFIRMED':
        direction = '顶部' if result.get('confirmedDirection') == 'TOP' else '底部'
        target = f'{time_text(result.get("confirmedAt"), period)} · 已形成{direction}结构'
        lines = ['等待新的钝化条件，再计算下一时点。']
    elif status == 'PRECISION_PENDING':
        lines.append('暂不提供结构条件；新收盘后更新。')
    elif status == 'DELAYED':
        target, lines = '行情尚未更新', ['等待新的已完成行情。']
    elif status == 'EMPTY':
        target, lines = '暂无完成行情', ['正式来源暂无完成行情。']
    elif status == 'NO_CANDIDATE':
        reasons = dict(NO_ENTRY_RANGE='当前没有可形成钝化的收盘条件。', ZERO_WAVE='当前MACD为零柱，等待有效柱段。',
                       NO_REFERENCE='同方向历史参照不足。', NO_CONFIRMATION_IN_HORIZON='当前没有可计算的结构条件。')
        if result.get('reasonCode') == 'NO_CONFIRMATION_IN_HORIZON' and not result.get('rearmContext'):
            labels[status] = f'{side}钝化有效'
            lines = [f'当前{side}钝化有效，后续结构时点暂未找到。',
                     f'{side}钝化消失或出现零柱时，原条件失效。', '本周期新收盘后重新判断。']
        else:
            lines = [reasons.get(result.get('reasonCode'), '当前没有可计算的结构条件。'), '本周期新收盘后重新判断。']
    if result.get('rearmContext'):
        labels[status] = '结构消失，待重新钝化'
        lines.insert(0, '原底部结构已消失；当前未重新形成底钝化。')
        lines = [line.replace('钝化触发：', '重新钝化：') for line in lines]
        lines.append('参照DIF突破、MACD柱色改变或出现零柱时，本次等待条件结束。')
    return dict(statusLabel=labels[status], targetText=target, conditionsText='\n'.join(lines),
                asOfText=('历史回放 · ' if mode == 'REPLAY' else '') + '截至 ' + time_text(through, period))
