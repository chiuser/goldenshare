"""Section 34 P0: authenticated method comparison and bounded metadata audit only."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from threading import Timer
import time
from zipfile import ZipFile, ZIP_DEFLATED

from scripts.research.index_market.chan.stock_research_store import StockResearchStore

REPO = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class FeasibilitySpec:
    lake: str = '/Volumes/datasource/data_lake'
    start: str = '2021-09-09'
    end: str = '2026-09-08'
    warmup: int = 250
    liquidity_days: int = 60
    max_files: int = 123
    max_bytes: int = 80 * 1024**2
    max_paths: int = 100000
    max_queries: int = 30
    max_rows: int = 50000
    query_seconds: int = 30
    seconds: int = 180
    archive_bytes: int = 128 * 1024**2
    record_bytes: int = 20 * 1024**2
    output_bytes: int = 16 * 1024**2


SPEC = FeasibilitySpec()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_checked(path, limit, expected=None):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('missing, redirected or oversized evidence')
    data = path.read_bytes()
    if expected is not None and digest(data) != expected:
        raise ValueError('evidence fingerprint mismatch')
    return data


def compare_low(case, origin, rows):
    event = origin['event']
    if (origin['status'] != 'unique' or event['event_id'] not in case['event_ids']
            or event['code'] != case['code'] or event['signal_time'] != case['signal_time']):
        raise ValueError('case identity mismatch')
    anchor, signal = event['anchor_index'], event['signal_index']
    if not 0 <= anchor <= signal < len(rows):
        raise ValueError('future or invalid anchor')
    if rows[anchor]['time'] != event['anchor_time'] or rows[signal]['time'] != event['signal_time']:
        raise ValueError('case time mismatch')
    frame = origin['snapshot']
    line = frame['objects'][frame['refs']['point']['line']]
    if line['end']['time'] != event['anchor_time'] or line['end_value'] != rows[anchor]['low']:
        raise ValueError('pullback anchor mismatch')
    return dict(code=case['code'], event_id=event['event_id'], signal_time=event['signal_time'],
                anchor_time=event['anchor_time'], types=case['types'], old_low=case['frozen_low'],
                pullback_low=line['end_value'], equal=case['frozen_low'] == line['end_value'])


def historical_evidence():
    store = StockResearchStore()
    origin_root = REPO/'reports/stock_b3_origin_audit_20260914'
    manifest_data = read_checked(origin_root/'manifest.json', SPEC.record_bytes)
    manifest = json.loads(manifest_data)
    read_checked(origin_root/'evidence.zip', SPEC.archive_bytes, manifest['evidence_sha256'])
    comparisons = []
    with ZipFile(origin_root/'evidence.zip') as archive:
        for code in manifest['completed']:
            info = archive.getinfo(code+'.json')
            if info.file_size > SPEC.record_bytes:
                raise ValueError('origin member budget')
            cases = store.read(f'exits/{code}/cases.json')
            lookup = {eid: case for case in cases for eid in case['event_ids']}
            rows = store.read(f'calendar/{code}/input_60.json')
            origins = json.loads(archive.read(info))['origins']
            comparisons.extend(compare_low(lookup[eid], origin, rows) for eid, origin in origins.items())
    if len(comparisons) != 58 or len({x['event_id'] for x in comparisons}) != 58:
        raise ValueError('frozen B3 denominator mismatch')
    archive_root = REPO/'reports/index_market_history_20260913'
    inventory_data = read_checked(archive_root/'inventory.json', SPEC.record_bytes)
    inventory = json.loads(inventory_data)
    expected = inventory['archives']['resonance.zip']['sha256']
    read_checked(archive_root/'resonance.zip', SPEC.archive_bytes, expected)
    replayed = set(store.read('calendar/source.json')['codes']) | {'002245.SZ'}
    selected, ranked = set(), set()
    records = {}
    with ZipFile(archive_root/'resonance.zip') as archive:
        for info in archive.infolist():
            match = re.search(r'/units/(\d{6}\.(?:SH|SZ))/', info.filename)
            if match:
                replayed.add(match[1])
            name = info.filename
            if not name.endswith(('/pairs.json', '/top50.json', '/ranking.json')):
                continue
            if info.file_size > SPEC.record_bytes:
                raise ValueError('historical member budget')
            raw = archive.read(info)
            if digest(raw) != inventory['records'][name]['sha256']:
                raise ValueError('historical record fingerprint')
            values = json.loads(raw)
            codes = ({x['winner'] for x in values} | {x['control'] for x in values}
                     if name.endswith('/pairs.json') else {x['ts_code'] for x in values})
            # An unmatched historical control is explicitly null, not a stock identity.
            unmatched = sum(x.get('control') is None for x in values) if name.endswith('/pairs.json') else 0
            codes.discard(None)
            if any(not isinstance(c,str) or not re.fullmatch(r'\d{6}\.(SH|SZ)',c) for c in codes):
                raise ValueError('invalid historical stock identity')
            (ranked if name.endswith('/ranking.json') else selected).update(codes)
            records[name] = dict(n=len(codes), unmatched_controls=unmatched, sha256=digest(raw))
    store.verify_unchanged()
    return dict(comparisons=comparisons, replayed=sorted(replayed), selected=sorted(selected),
                ranked=sorted(ranked), records=records, consumed=store.consumed,
                fingerprints={str(origin_root/'manifest.json'): digest(manifest_data),
                              str(origin_root/'evidence.zip'): manifest['evidence_sha256'],
                              str(archive_root/'inventory.json'): digest(inventory_data),
                              str(archive_root/'resonance.zip'): expected})


def eligible(stock, start=SPEC.start):
    return (stock['exchange'] in ('SSE', 'SZSE') and stock['curr_type'] == 'CNY'
            and stock['list_status'] == 'L' and stock['delist_date'] is None
            and stock['list_date'] is not None and str(stock['list_date']) <= start
            and bool(re.fullmatch(r'(?:60\d{4}|68\d{4})\.SH|(?:00\d{4}|30\d{4})\.SZ', stock['ts_code'])))


class Queries:
    def __init__(self, paths, started):
        import duckdb
        if len(paths) > SPEC.max_files or sum(p.stat().st_size for p in paths) > SPEC.max_bytes:
            raise ValueError('parquet budget')
        if any(p.is_symlink() for p in paths):
            raise ValueError('redirected parquet')
        self.started, self.log = started, []
        self.connection = duckdb.connect(':memory:', config={
            'threads': 2, 'memory_limit': '1GiB', 'max_temp_directory_size': '0B',
            'allow_persistent_secrets': False, 'autoinstall_known_extensions': False,
            'autoload_known_extensions': False})
        self.connection.execute('SET allowed_paths = ?', [[str(p) for p in paths]])
        self.connection.execute('SET enable_external_access=false')
        self.connection.execute('SET lock_configuration=true')

    def run(self, sql, params=None):
        if len(self.log) >= SPEC.max_queries or time.monotonic()-self.started > SPEC.seconds:
            raise TimeoutError('audit budget')
        started = time.monotonic()
        timer = Timer(SPEC.query_seconds, self.connection.interrupt)
        timer.start()
        try:
            cursor = self.connection.execute(sql, params or [])
            columns = [x[0] for x in cursor.description]
            data = cursor.fetchmany(SPEC.max_rows+1)
            if len(data) > SPEC.max_rows:
                raise ValueError('result row budget')
            result = [dict(zip(columns, row, strict=True)) for row in data]
        finally:
            timer.cancel()
        self.log.append(dict(sql=sql, params=params, rows=len(result), seconds=time.monotonic()-started))
        return result


def lake_audit(history, started):
    lake = Path(SPEC.lake)
    basic = lake/'silver/basic/stock_basic/full/part-000.parquet'
    lifecycle = lake/'silver/basic/stock_lifecycle/full/part-000.parquet'
    calendar = lake/'silver/calendar/trade_calendar/full/part-000.parquet'
    initial = Queries([basic, lifecycle, calendar], started)
    days = [x['cal_day'] for x in initial.run(
        'SELECT CAST(trade_date AS VARCHAR) AS cal_day FROM read_parquet(?,hive_partitioning=false) '
        'WHERE exchange=\'SSE\' AND is_open AND trade_date BETWEEN ? AND ? ORDER BY trade_date',
        [str(calendar), SPEC.start, SPEC.end])]
    initial.connection.close()
    if len(days) != len(set(days)) or len(days) <= SPEC.warmup:
        raise ValueError('invalid calendar')
    dates = days[SPEC.warmup-SPEC.liquidity_days:SPEC.warmup]
    daily = [lake/f'silver/quote/stock_daily/trade_date={d}/part-000.parquet' for d in dates]
    susp = [lake/f'silver/quote/stock_suspend_daily/trade_date={d}/part-000.parquet' for d in dates]
    expected_paths = [basic, lifecycle, calendar, *daily, *susp]
    paths = [p for p in expected_paths if p.is_file()]
    q = Queries(paths, started)
    q.log.extend(initial.log)
    before = {str(p): dict(bytes=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns,
                           sha256=digest(read_checked(p, SPEC.max_bytes))) for p in paths}
    stocks = q.run('SELECT ts_code,exchange,market,curr_type,list_status,list_date,delist_date '
                   'FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code', [str(basic)])
    life = q.run('SELECT ts_code,exchange,curr_type,list_status,list_date,delist_date '
                 'FROM read_parquet(?,hive_partitioning=false)', [str(lifecycle)])
    life_map = {x['ts_code']: x for x in life}
    if len(life_map) != len(life) or len({x['ts_code'] for x in stocks}) != len(stocks):
        raise ValueError('duplicate identity')
    pool = [x for x in stocks if eligible(x)]
    mismatches = [x['ts_code'] for x in pool if x['ts_code'] not in life_map or
                  any(x[k] != life_map[x['ts_code']][k] for k in ('exchange','curr_type','list_status','list_date','delist_date'))]
    seen = set(history['replayed']) | set(history['selected'])
    ranked = set(history['ranked'])
    inventory = []
    checks = 0
    for stock in pool:
        if time.monotonic()-started > SPEC.seconds:
            raise TimeoutError('file inventory budget')
        code = stock['ts_code']
        files = [lake/f'gold/quote/stk_mins_qfq/freq={freq}/ts_code={code}/year={y}/part-000.parquet'
                 for freq in (30,60) for y in range(2021,2027)]
        checks += len(files)
        if checks > SPEC.max_paths:
            raise ValueError('path budget')
        available = [p for p in files if p.is_file() and not p.is_symlink()]
        inventory.append(dict(code=code, board=f"{stock['exchange']}/{stock['market']}",
                              seen=code in seen, ranked=code in ranked,
                              missing=[str(p.relative_to(lake)) for p in files if p not in available],
                              bytes=sum(p.stat().st_size for p in available)))
    # Metadata feasibility is not minute-series completeness or a source API contract audit.
    schemas = {}
    for label, path in [('basic',basic), ('lifecycle',lifecycle), ('daily',daily[-1])]:
        if path.is_file():
            schemas[label] = q.run('DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)', [str(path)])
    liquidity = []
    if all(p.is_file() for p in daily+susp):
        q.run('CREATE TEMP TABLE d AS SELECT ts_code,trade_date,amount FROM read_parquet(?,hive_partitioning=false)', [[str(p) for p in daily]])
        q.run("CREATE TEMP TABLE s AS SELECT ts_code,trade_date, bool_or(suspend_type='S' AND trim(coalesce(suspend_timing,''))='') AND NOT bool_or(suspend_type='R') full_day FROM read_parquet(?,hive_partitioning=false) GROUP BY ALL", [[str(p) for p in susp]])
        duplicate = q.run('SELECT count(*) n FROM (SELECT ts_code,trade_date FROM d GROUP BY ALL HAVING count(*)>1)')[0]['n']
        if duplicate:
            raise ValueError('duplicate daily keys')
        liquidity = q.run("WITH pool AS (SELECT unnest(?::VARCHAR[]) ts_code), days AS (SELECT unnest(?::DATE[]) trade_date) SELECT p.ts_code, count(d.amount) present, count(*) FILTER(WHERE d.ts_code IS NULL AND coalesce(s.full_day,false)) full_suspend, count(*) FILTER(WHERE d.ts_code IS NULL AND NOT coalesce(s.full_day,false)) unexplained_missing, count(*) FILTER(WHERE d.ts_code IS NOT NULL AND (d.amount IS NULL OR NOT isfinite(d.amount) OR d.amount<0)) invalid_amount, count(*) FILTER(WHERE d.ts_code IS NOT NULL AND coalesce(s.full_day,false)) conflicting_presence, sum(d.amount)/60 mean_amount FROM pool p CROSS JOIN days t LEFT JOIN d ON d.ts_code=p.ts_code AND d.trade_date=t.trade_date LEFT JOIN s ON s.ts_code=p.ts_code AND s.trade_date=t.trade_date GROUP BY p.ts_code ORDER BY p.ts_code", [[x['ts_code'] for x in pool], dates])
    q.connection.close()
    for row in liquidity:
        if row['unexplained_missing'] or row['invalid_amount'] or row['conflicting_presence']:
            row['mean_amount'] = None
    for path, fact in before.items():
        if digest(read_checked(Path(path), SPEC.max_bytes)) != fact['sha256']:
            raise ValueError('lake input changed during audit')
    boards = []
    for board in sorted({x['board'] for x in inventory}):
        xs = [x for x in inventory if x['board'] == board]
        boards.append(dict(board=board, eligible=len(xs), seen=sum(x['seen'] for x in xs),
                           not_selected=sum(not x['seen'] for x in xs),
                           never_ranked=sum(not x['ranked'] and not x['seen'] for x in xs),
                           missing_minute_files=sum(bool(x['missing']) for x in xs)))
    return dict(stock_rows=len(stocks), markets=dict(Counter(x['exchange'] for x in stocks)),
                days=len(days), evaluation_start=days[SPEC.warmup], size_date=dates[-1],
                liquidity_start=dates[0], calendar_60day_blocks=(len(days)-SPEC.warmup)//60,
                boards=boards, identity_mismatches=mismatches, stock_inventory=inventory,
                liquidity=liquidity, schemas=schemas, files=before,
                missing_source_files=[str(p) for p in expected_paths if not p.is_file()],
                path_checks=checks, queries=q.log)


def execute(output):
    output = output.absolute()
    if output.parent != REPO/'reports' or output.exists() or output.is_symlink():
        raise ValueError('output must be a new direct reports child')
    started = time.monotonic()
    history = historical_evidence()
    print('method comparison and historical exposure complete', flush=True)
    lake = lake_audit(history, started)
    same = sum(x['equal'] for x in history['comparisons'])
    liq = lake['liquidity']
    summary = dict(method_equal=same, method_total=58,
                   replayed=len(history['replayed']), selected=len(history['selected']),
                   ranked=len(history['ranked']), boards=lake['boards'],
                   liquidity_stocks=len(liq),
                   liquidity_unexplained_days=sum(x['unexplained_missing'] for x in liq),
                   liquidity_full_suspend_days=sum(x['full_suspend'] for x in liq),
                   liquidity_invalid_stocks=sum(x['invalid_amount']>0 for x in liq),
                   liquidity_conflicting_stocks=sum(x['conflicting_presence']>0 for x in liq))
    report = '\n'.join([
        '# 扩样P0：停止于样本设计门禁，未运行新收益', '',
        f'旧58次B3低点逐笔相同：{same}/58。混合类型保留；没有新增退出回测。', '',
        '## 股票身份与历史接触', '',
        '| 板块 | 五年前已上市 | 已选入案例/对照或回放 | 未选入这些名单 | 既未排名也未选入 | 缺年度分钟文件 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |',
        *[f"| {b['board']} | {b['eligible']} | {b['seen']} | {b['not_selected']} | {b['never_ranked']} | {b['missing_minute_files']} |" for b in lake['boards']], '',
        f"历史回放身份{summary['replayed']}，领涨/对照身份{summary['selected']}，排名计算身份{summary['ranked']}；集合重叠，不可相加。", '',
        '排名参与不等于研究者逐只查看，但也不能把它们称为完全未使用过的数据。名单未冻结，未抽股。', '',
        '## 数据范围与缺口', '',
        f"日历{lake['days']}个市场交易日；初始化后起点{lake['evaluation_start']}；历史市值基准日{lake['size_date']}。",
        f"成交额窗口{lake['liquidity_start']}—{lake['size_date']}，60个市场日；检查{len(liq)}股，解释为全日停牌的缺行{summary['liquidity_full_suspend_days']}股日，未知缺行{summary['liquidity_unexplained_days']}股日，非法金额股票{summary['liquidity_invalid_stocks']}，停牌与日线同时存在股票{summary['liquidity_conflicting_stocks']}。",
        '正式Lake路径/catalog及基础/日线schema未找到个股历史总市值；12层市值分组不能完成。不用板块市值或成交额替代。',
        '股票基本信息与生命周期是现存快照；manifest记录文件时间和哈希，不将文件修改时间当成源端业务截至日。抽样前须再次核验存续状态。', '',
        '## 检查边界', '',
        f"分钟线只检查{lake['path_checks']}个年度路径和文件大小，没有扫描分钟OHLC/时点，因此零缺文件也不等于完整可回测。",
        f"初始化后可划{lake['calendar_60day_blocks']}个完整不重叠60市场日窗口；这不是独立牛熊周期数，更不是有效信号数。",
        '方法证据逐笔校验、基础身份核对和60日成交额缺行检查完成；未计算新信号、收益、显著性、抽样名单或正式ready。', '',
        '## 下一步须先决定', '',
        '补齐获准历史市值来源，或另行批准更简化的分层设计；同时明确旧全市场排名接触的隔离口径。当前不进入P1。', '',
        '机器证据见evidence.zip；规格、SQL、文件指纹与耗时见manifest及包内记录。', ''])
    output.mkdir()
    (output/'report.md').write_text(report)
    selection = {k:history[k] for k in ('replayed','selected','ranked')}
    selection['status'] = 'exposure_inventory_only_no_sampling'
    (output/'selection.json').write_bytes(encoded(selection))
    with ZipFile(output/'evidence.zip', 'x', compression=ZIP_DEFLATED) as archive:
        archive.writestr('method_and_history.json', encoded(history))
        archive.writestr('lake_audit.json', encoded(lake))
    manifest = dict(status='p0_blocked_no_sampling', spec=asdict(SPEC), summary=summary,
                    seconds=time.monotonic()-started, as_of=datetime.now().astimezone().isoformat(),
                    code_sha256=digest(Path(__file__).read_bytes()),
                    plan_sha256=digest((REPO/'docs/product/stock-chan-share-position-backtest-plan-v1.md').read_bytes()),
                    artifact_sha256={p.name:digest(p.read_bytes()) for p in output.iterdir()})
    (output/'manifest.json').write_bytes(encoded(manifest))
    if sum(p.stat().st_size for p in output.iterdir()) > SPEC.output_bytes:
        raise ValueError('output budget')
    print(json.dumps(dict(summary=summary, seconds=manifest['seconds']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    execute(parser.parse_args().output)
