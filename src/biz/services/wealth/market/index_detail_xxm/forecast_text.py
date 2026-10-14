"""Candidate deterministic Chinese copy. Production does not import reports."""
from .forecast_math import as_interval,display_range
from .forecast_spec import FORECAST_SPEC


def time_text(value,period):
    if value is None:return '--'
    return value[5:10].replace('-','/')+(' 收盘' if period=='day' else ' '+value[11:16]+' 这一根收盘')


def range_text(r,places=FORECAST_SPEC.price_display_places):
    value=display_range(as_interval(r),places)
    if value is None:return '边界过窄，暂不能可靠显示'
    lo,hi=value['displayLower'],value['displayUpper'];n=value['displayPlaces']
    if hi is None:return f'至少 {lo:.{n}f} 点'
    if r['lower']==0:return f'不高于 {hi:.{n}f} 点'
    return f'{lo:.{n}f}～{hi:.{n}f} 点'


def make_display(result,period,through,mode):
    status=result['status'];direction='顶部' if result.get('direction')=='TOP' else '底部'
    side='顶' if direction=='顶部' else '底'
    labels=dict(READY=f'{side}钝化有效',CONDITIONAL_ENTRY=f'需先形成{side}钝化',ENTRY_ONLY='可算钝化范围',NO_CANDIDATE='暂无条件',CONFIRMED='已确认',PRECISION_PENDING='边界待核验',DELAYED='数据滞后',EMPTY='暂无数据')
    target='暂未找到可计算的结构时点'
    lines=[]
    activation=result.get('activation')
    if activation and activation['ranges']:
        t=time_text(activation['endpoint'],period)
        lines.append(f'先看钝化：{t}落在以下范围，可出现{side}钝化。')
        for i,group in enumerate(activation['ranges'],1):
            label=f'范围{i}：' if len(activation['ranges'])>1 else ''
            lines.append(label+range_text(group['priceRange'],FORECAST_SPEC.price_boundary_places)+'（边界向内保留）。')
        failure_names=dict(PRICE_NOT_EXTREME=f'尚未跨过能保持背离的参考{"高" if side=="顶" else "低"}点',DIF_NOT_DIVERGENT=f'指标也创新{"高" if side=="顶" else "低"}，背离条件不成立',WRONG_COLOR_OR_ZERO='MACD柱色已改变或到了零柱，需重新判断',INSUFFICIENT_BARS='同色柱根数不足')
        for part in activation['exclusions']:
            if part['reason']=='PRECISION_UNRESOLVED':continue
            shown=display_range(as_interval(part['priceRange']),FORECAST_SPEC.price_boundary_places)
            if shown and (shown['displayUpper'] is None or shown['displayUpper']-shown['displayLower']>.0001):
                lines.append('不成立的情况：'+range_text(part['priceRange'],FORECAST_SPEC.price_boundary_places)+'，'+failure_names.get(part['reason'],'条件不足')+'。')
        if any(p['reason']=='PRECISION_UNRESOLVED' for p in activation['exclusions']):lines.append('取整或数值边界附近暂不作触发承诺。')
    if status in ('READY','CONDITIONAL_ENTRY'):
        target=f'{time_text(result["targetEndpoint"],period)} · {direction}结构条件'
        if status=='READY':lines.append(f'当前{side}钝化有效。')
        if result['barsAhead']>(2 if activation else 1):lines.append('时间推演暂按目标前的中间收盘持平；实际走势改变后重算。')
        if activation:
            domains=result.get('targetEntryRanges',[])
            lines.append('这个时点适用的前置收盘范围：'+'；'.join(range_text(g['priceRange'],FORECAST_SPEC.price_boundary_places) for g in domains)+'。')
        for excluded in result.get('targetEntryExclusions',[]):
            shown=display_range(as_interval(excluded['priceRange']),FORECAST_SPEC.price_boundary_places)
            if shown is None:continue
            reason_names=dict(CANCEL_BEFORE_TARGET=f'原{side}钝化会先消失',EARLY_STRUCTURE='按持平假设，结构会在更早一根出现',COLOR_OR_ZERO='中间柱色已改变或出现零柱',NO_TARGET_SOLUTION='在这个时点没有符合条件的结构收盘价',PRECISION_UNRESOLVED='取整边界暂不能可靠判断')
            lines.append('这个时点不适用：前置收盘 '+range_text(excluded['priceRange'],FORECAST_SPEC.price_boundary_places)+'，'+reason_names[excluded['reason']]+'。')
        common=result.get('commonConditions',[])
        if common:
            for group in common:
                route='指标向下转折' if side=='顶' else '指标向上转折'
                if group['route']=='color_flip':route='MACD红柱变绿' if side=='顶' else 'MACD绿柱变红'
                prefix='对前置收盘在 '+range_text(group['entryDomain'],FORECAST_SPEC.price_boundary_places)+' 的情况，' if group['entryDomain'] else ''
                prices='；或 '.join(range_text(r) for r in group['closeRanges'])
                lines.append(prefix+f'目标收盘满足 {prices}，可形成{direction}结构（{route}）。')
            if activation:lines.append('以上是对所列前置范围都成立的充分条件；其他价格组合按前置收盘分别计算。')
        else:lines.append('结构门槛随前一根收盘变化，没有对整个前置范围都成立的统一点位。')
        if activation and result.get('examples'):
            lines.append('差异举例（不要求收在这些示例点）：')
            for e in result['examples']:
                prices='；或 '.join(range_text(r) for r in e['closeRanges'])
                lines.append(f'前置收盘 {e["preClose"]:.{2 if round(e["preClose"],2)==e["preClose"] else 4}f} 点 → 目标收盘 {prices}。')
            lines.append('实际收盘到达后，会更新它对应的条件。')
        lines.append(f'原{side}钝化消失、出现零柱或中间走势改变时，旧条件不再直接适用；目标未达条件不等于钝化已消失。')
    elif status=='ENTRY_ONLY':lines.append('能算出钝化范围，但未来20根内暂未找到后续结构时点；不代表以后不会出现结构。')
    elif status=='CONFIRMED':
        cd='顶部' if result.get('confirmedDirection')=='TOP' else '底部'
        target=f'{time_text(result.get("confirmedAt"),period)} · 已形成{cd}结构'
        lines=['等待新的钝化条件，再计算下一候选。']
    elif status=='DELAYED':target='行情尚未更新';lines=['等待新的已完成行情，暂不提供当前预判。']
    elif status=='EMPTY':target='暂无完成行情';lines=['正式来源暂无完成行情。']
    elif status=='PRECISION_PENDING':lines.append('指标或价格处于精度临界，暂不能可靠给出结构点位；不跳到更晚时点。')
    else:
        reason=result.get('reasonCode')
        reason_names=dict(NO_ENTRY_RANGE='当前没有可形成钝化的收盘范围。',ZERO_WAVE='当前MACD为零柱，等待有效柱段。',NO_REFERENCE='同方向历史参照不足。',NO_CONFIRMATION_IN_HORIZON='当前假设下，未来20根内暂未找到结构条件。')
        lines.append(reason_names.get(reason,'暂未找到可靠条件。'))
    condition_text='\n'.join(lines)
    return dict(statusLabel=labels[status],targetText=target,conditionsText=condition_text,asOfText=('历史回放 · ' if mode=='REPLAY' else '')+'截至 '+time_text(through,period))
