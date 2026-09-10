"""Independent SQL/window and batch-candidate verification for C1."""
from __future__ import annotations

import math

import duckdb
import pandas as pd


def reference_candidates(rows, ctx, frequency, spec):
    """Enumerate crossings first, then scan each disjoint bounded candidate window."""
    window = (240//frequency)*spec.wait_days
    crossings = [i for i in range(1,len(rows)) if ctx[i]['level'] is not None
                 and ctx[i]['atr20'] is not None and ctx[i]['atr20']>0
                 and rows[i-1]['close']<=ctx[i]['level']<rows[i]['close']]
    locked_until, days_started, result, triggers = -1, set(), [], []
    for i in crossings:
        if i<=locked_until or rows[i]['date'] in days_started:
            continue
        days_started.add(rows[i]['date'])
        level, tol = ctx[i]['level'], spec.tolerance_atr*ctx[i]['atr20']
        terminal = None
        for j in range(i+1,min(i+window+1,len(rows))):
            r = rows[j]
            if r['close']<=level or r['low']<level-tol:
                terminal = (j,'failed')
                break
            if level-tol<=r['low']<=level+tol and level<r['close']<rows[j-1]['close']:
                terminal = (j,'triggered')
                triggers.append(j)
                break
        if terminal is None and i+window<len(rows):
            terminal = (i+window,'expired')
        locked_until = terminal[0] if terminal else len(rows)-1
        result.append(dict(breakout_index=i, breakout_time=rows[i]['time'],level=level,tolerance=tol,
            status=terminal[1] if terminal else 'pending_at_end',end_index=terminal[0] if terminal else None,
            end_time=rows[terminal[0]]['time'] if terminal else None))
    return result, triggers


def verify_cell(rows, days, ctx, simple, candidates, labels, methods, stats, frequency, spec):
    from scripts.research.index_market.chan.minute_comparison import contexts, simple_signals

    frame = pd.DataFrame(rows)
    frame['idx'] = range(len(rows))
    checks = {}
    with duckdb.connect(':memory:',config={'threads':4,'memory_limit':'1GiB',
            'max_temp_directory_size':'0B','enable_external_access':False,
            'allow_persistent_secrets':False,'autoinstall_known_extensions':False,
            'autoload_known_extensions':False}) as con:
        con.register('prices',frame)
        con.execute('''CREATE TEMP TABLE daily AS WITH d AS (
            SELECT date, max(high) AS high, min(low) AS low, arg_max(close,idx) AS close,
                   max(idx) AS end_index FROM prices GROUP BY date), p AS (
            SELECT *, lag(close) OVER(ORDER BY date) AS prev_close FROM d)
            SELECT *, CASE WHEN prev_close IS NOT NULL THEN
              greatest(high-low,abs(high-prev_close),abs(low-prev_close)) END AS tr FROM p''')
        con.execute(f'''CREATE TEMP TABLE dc AS SELECT *,
            max(high) OVER(ORDER BY date ROWS BETWEEN {spec.breakout_days} PRECEDING AND 1 PRECEDING) AS ref,
            avg(tr) OVER(ORDER BY date ROWS BETWEEN {spec.atr_days} PRECEDING AND 1 PRECEDING) AS atr,
            lag(close,{spec.trend_days}) OVER(ORDER BY date) AS trend_base,
            avg(tr/prev_close) OVER(ORDER BY date ROWS BETWEEN {spec.atr_days} PRECEDING AND 1 PRECEDING)
              /nullif(avg(tr/prev_close) OVER(ORDER BY date ROWS BETWEEN {spec.volatility_days} PRECEDING AND 1 PRECEDING),0) AS vol,
            lead(close) OVER(ORDER BY date) AS next_close,
            lead(date) OVER(ORDER BY date) AS next_date,
            lead(end_index) OVER(ORDER BY date) AS next_end FROM daily''')
        actual = con.execute('''SELECT p.idx,d.ref,d.atr,p.close/d.trend_base-1,d.vol
            FROM prices p JOIN dc d USING(date) ORDER BY p.idx''').fetchall()
        for i, level, atr, trend, vol in actual:
            if i not in labels:
                continue
            for key, value in zip(('level','atr20','trend_return','volatility_ratio'),(level,atr,trend,vol)):
                if value is None or not math.isclose(ctx[i][key],value,rel_tol=1e-10,abs_tol=1e-10):
                    raise ValueError(f'SQL background mismatch {i}/{key}: {ctx[i][key]} vs {value}')
            trend_up = trend>=0 or math.isclose(trend,0,abs_tol=spec.comparison_epsilon)
            vol_high = vol>=1 or math.isclose(vol,1,rel_tol=spec.comparison_epsilon,abs_tol=spec.comparison_epsilon)
            if ctx[i]['background']!=f'{int(trend_up)}|{int(vol_high)}':
                raise ValueError('SQL background classification mismatch')
        con.execute('''CREATE TEMP TABLE paths AS WITH p AS (
              SELECT *, lead(open) OVER(ORDER BY idx) AS entry,
                lead(time) OVER(ORDER BY idx) AS entry_time FROM prices)
            SELECT p.idx,p.date,p.time,p.entry_time,p.entry,d.next_date,
              d.next_close/p.close-1 AS r,d.next_close/p.entry-1 AS q,
              d.next_end, a.lo/p.entry-1 AS mae,a.hi/p.entry-1 AS mfe
            FROM p JOIN dc d USING(date) LEFT JOIN LATERAL (
              SELECT min(low) AS lo,max(high) AS hi FROM prices f
              WHERE f.idx>p.idx AND f.idx<=d.next_end) a ON true
            WHERE d.next_date IS NOT NULL''')
        sql_labels = con.execute('SELECT * FROM paths ORDER BY idx').fetchall()
        for i, day, ts, entry_time, entry, next_day, r, q, end, mae, mfe in sql_labels:
            if i not in labels:
                continue
            label = labels[i]
            assert label['target_time']==rows[end]['time'] and next_day==days[days.index(day)+1]
            assert label['signal_time']==ts and label['entry_bar_end']==entry_time
            for key,value in dict(entry=entry,r=r,q=q,mae=mae,mfe=mfe).items():
                assert math.isclose(label[key],value,rel_tol=1e-10,abs_tol=1e-10),(i,key)
        # Independent aggregation joins are keyed by one label per index.
        con.register('label_frame',pd.DataFrame(list(labels.values())))
        con.execute('''CREATE TEMP TABLE baselines AS SELECT stratum,count(*) AS n,
            avg(up) AS up,avg(q) AS q FROM label_frame GROUP BY stratum''')
        event_frame = pd.DataFrame([dict(method=m,idx=e['signal_index']) for m,ee in methods.items() for e in ee],columns=['method','idx'])
        con.register('event_frame',event_frame)
        con.execute(f'''CREATE TEMP TABLE supported AS SELECT e.method,l.*,
            l.up-b.up AS lu,l.q-b.q AS lq FROM event_frame e
            JOIN label_frame l ON e.idx=l.index JOIN baselines b USING(stratum)
            WHERE b.n>={spec.min_baseline_bars}''')
        for method in ('simple','chan'):
            n,up,q,lu,lq = con.execute('SELECT count(*),avg(up),avg(q),avg(lu),avg(lq) FROM supported WHERE method=?',[method]).fetchone()
            expected = stats['modes']['cooldown'][method]['supported']
            assert n==expected['n']
            for key,v in zip(('up','q','lift_up','lift_q'),(up,q,lu,lq)):
                assert (v is None and expected[key] is None) or (v is not None and math.isclose(v,expected[key],abs_tol=1e-10))
        direct = con.execute('''WITH g AS (SELECT method,stratum,count(*) AS n,avg(up) AS u,avg(q) AS q
              FROM supported GROUP BY method,stratum), pairs AS (
              SELECT s.n AS sn,c.n AS cn,c.u-s.u AS du,c.q-s.q AS dq
              FROM g s JOIN g c USING(stratum) WHERE s.method='simple' AND c.method='chan')
            SELECT count(*),coalesce(sum(sn),0),coalesce(sum(cn),0),
              sum((sn+cn)*du)/sum(sn+cn),sum((sn+cn)*dq)/sum(sn+cn) FROM pairs''').fetchone()
        expected = stats['modes']['cooldown']['direct']
        for key,v in zip(('strata','simple_n','chan_n','delta_up','delta_q'),direct):
            assert (v is None and expected[key] is None) or (v is not None and math.isclose(v,expected[key],abs_tol=1e-10)),key
        checks.update(sql_background_bars=len(labels),sql_label_paths=len(labels),sql_supported_and_common_estimates=True)
    reference, triggers = reference_candidates(rows,ctx,frequency,spec)
    assert reference==candidates and triggers==[e['signal_index'] for e in simple]
    checks.update(independent_candidates=len(candidates),independent_simple_triggers=len(simple))
    prefixes = []
    for cutoff in spec.prefix_dates:
        n = sum(r['date']<=cutoff for r in rows)
        before = rows[:n]
        short_ctx = contexts(before,spec)
        assert short_ctx==ctx[:n]
        assert simple_signals(before,short_ctx,frequency,spec)[0]==[e for e in simple if e['signal_index']<n]
        altered = before+[{**r,**{k:r[k]*1.1 for k in ('open','high','low','close')}} for r in rows[n:]]
        altered_ctx = contexts(altered,spec)
        assert altered_ctx[:n]==ctx[:n]
        assert [e for e in simple_signals(altered,altered_ctx,frequency,spec)[0] if e['signal_index']<n]==[e for e in simple if e['signal_index']<n]
        prefixes.append(dict(cutoff=cutoff,bars=n,unchanged=True))
    checks['prefix_and_future_perturbation'] = prefixes
    return checks
