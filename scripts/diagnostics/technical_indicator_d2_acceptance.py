"""Bounded D2 acceptance, LLD 19.8; never a production calculation entry.

Only the two named existing temporary samples and four named Lake files may be
read. No source file is created or changed. Each completed stage is persisted
before the next stage starts, including failures and cleanup evidence.
"""

from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import resource
import sys
from time import monotonic

import pyarrow.dataset as ds
import pyarrow.fs as fs
import pyarrow.parquet as pq

from src.foundation.config.settings import Settings
from src.foundation.clients.local_lake.technical_indicator_contracts import price_contract, source_projection
from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource, _LakePriceStream
from src.foundation.technical_indicators import CalculationInstance, CalculationRequest
from src.foundation.technical_indicators.calculation.history import HistoryRequirement
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.execution_control import ExecutionControl
from src.foundation.technical_indicators.service import TechnicalIndicatorService
from src.foundation.technical_indicators.sources.contracts import ReadRequirement, SourceDescription
from src.foundation.technical_indicators.sources.read_context import SourceReadContext
from src.foundation.technical_indicators.sources.session import PriceInputSession

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path('/private/tmp/indicator_lld_probe_20261022/fixture.parquet')
WRONG_FIXTURE = Path('/private/tmp/ti_reader_interleave_20261022/large.parquet')
OUTPUT = ROOT / 'reports/technical_indicator_kernel_d2_20261023/acceptance.json'
EXPECTED_ROWS = 32768
BATCH_ROWS = 8192


def inspect_fixture(path):
    """Footer-only work, before any Scanner or DuckDB connection is created."""
    size = path.stat().st_size
    with pq.ParquetFile(path) as parquet:
        metadata = parquet.metadata
        names = parquet.schema_arrow.names
        projected = ('i', 'trade_time', 'close')
        if not set(projected) <= set(names):
            raise ValueError('The diagnostic sample lacks its declared columns')
        largest = max((sum(metadata.row_group(i).column(j).total_uncompressed_size
                           for j in range(metadata.num_columns)
                           if metadata.schema.column(j).name in projected)
                       for i in range(metadata.num_row_groups)), default=0)
        return dict(path=str(path), bytes=size, rows=metadata.num_rows,
                    projected_row_group_bytes=largest)


def validate_fixture(metadata):
    if metadata['rows'] != EXPECTED_ROWS:
        raise ValueError(f"Expected exactly {EXPECTED_ROWS} fixture rows; got {metadata['rows']}")
    if metadata['bytes'] > 8 * 1024 * 1024:
        raise ValueError('The diagnostic sample exceeds 8MiB')
    if metadata['projected_row_group_bytes'] > 32 * 1024 * 1024:
        raise ValueError('The diagnostic projected row group exceeds 32MiB')


class CheckedReader:
    """Keep one real reader, checking delivered positions before SQL receives them."""
    def __init__(self, reader, *, scanner=None, fragment=None):
        self.reader, self.scanner, self.fragment = reader, scanner, fragment
        self.rows = self.batches = 0

    def read_next_batch(self):
        batch = self.reader.read_next_batch()  # Normal EOF still comes from this reader.
        rows = batch.num_rows
        if rows == 0:
            return batch
        if (rows > BATCH_ROWS or self.batches >= 4 or self.rows + rows > EXPECTED_ROWS):
            raise ValueError('The next sample batch exceeds the approved row/batch budget')
        # i is source position metadata in this diagnostic fixture, never an
        # indicator value. Check actual source positions as well as generated seq.
        positions = batch.column('i')
        if positions[0].as_py() != self.rows or positions[-1].as_py() != self.rows + rows - 1:
            raise ValueError('The fixture reader restarted or skipped source positions')
        self.rows += rows
        self.batches += 1
        return batch

    def close(self):
        if self.reader is not None:
            self.reader.close()
            self.reader = self.scanner = self.fragment = None


def create_fixture_reader(path):
    fragment = ds.ParquetFileFormat().make_fragment(str(path), filesystem=fs.LocalFileSystem())
    scanner = ds.Scanner.from_fragment(fragment, columns=['i', 'trade_time', 'close'],
        batch_size=BATCH_ROWS, batch_readahead=0, fragment_readahead=0,
        use_threads=False, cache_metadata=False,
        fragment_scan_options=ds.ParquetFragmentScanOptions(pre_buffer=False, use_buffered_stream=False))
    return CheckedReader(scanner.to_reader(), scanner=scanner, fragment=fragment)


def open_checked_fixture(path):
    metadata = inspect_fixture(path)
    validate_fixture(metadata)
    return metadata, create_fixture_reader(path)


def persist(report):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n')
    os.replace(temporary, OUTPUT)


def peak_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == 'darwin' else value * 1024


def verify_fixture(config, report):
    metadata = inspect_fixture(FIXTURE)
    validate_fixture(metadata)
    report['fixture_preflight'] = metadata
    persist(report)
    # Recheck before opening, so the standalone helper enforces the same rule.
    metadata, reader = open_checked_fixture(FIXTURE)
    control = ExecutionControl(arrived_at=monotonic(), config=config)
    report['control_objects'] += 1
    service = TechnicalIndicatorService(source=None, registry=None, config=config)
    connection = inputs = None
    context = SourceReadContext(config)
    context.record_file(FIXTURE, metadata['bytes'])
    request = CalculationRequest('stock', '600000.SH', '1m', (CalculationInstance('ma', 'ma', {}),))
    requirement = ReadRequirement(request, HistoryRequirement(frozenset(('close',)), 0, True, (),
        initial_null_rule='diagnostic fixture'), BATCH_ROWS, None, None)
    description = SourceDescription('diagnostic_fixture', '1', 'qfq', 'fixture', None, None,
        'CNY', 'share', 'CNY', 'Asia/Shanghai', 'trade_time', 'fixture_start', None, False,
        (('qfq', 'qfq'),), False, source_projection=('i', 'trade_time', 'close'),
        standard_projection=(('trade_date', 'CAST(b.trade_time AS DATE)'),
                             ('trade_time', 'CAST(b.trade_time AS TIMESTAMP)'),
                             ('close', 'CAST(b.close AS DOUBLE)')))
    stage = report['fixture'] = dict(status='running', batches=[], source_rows=0)
    try:
        connection, executor = service._open_execution(control)
        stream = _LakePriceStream(description, requirement, control, context)
        stream._reader = reader  # Only file access is selected; actual stream/session execute.

        class Source:
            def open(self, *args, **kwargs):
                return stream

        inputs = PriceInputSession(executor, Source(), description, requirement, read_context=context)
        inputs.prepare()
        while (batch := inputs.next_batch()) is not None:
            if len(stage['batches']) >= 4:
                raise ValueError('The sample must not deliver a fifth price batch')
            actual = executor.scalar('SELECT struct_pack(n:=count(*),lo:=min(seq),hi:=max(seq)) FROM ti_price_window')
            number = len(stage['batches'])
            assert actual == dict(n=8192, lo=number*8192+1, hi=(number+1)*8192)
            assert stream._current_batch is None
            stage['batches'].append(actual)
            stage['source_rows'] = context.source_rows
            inputs.retain_required_history()
            inputs.finish_batch()
            persist(report)
        assert reader.rows == context.source_rows == EXPECTED_ROWS and reader.batches == 4
        stage.update(status='passed', sql_steps=len(executor.statistics), sql_logical_rows=executor.sql_processed_rows)
    finally:
        errors = service._close_execution(control, connection, inputs=inputs)
        # If connection or session construction failed, the diagnostic still owns reader.
        try:
            reader.close()
        except BaseException as exc:
            errors += (exc,)
        stage['cleanup_errors'] = [f'{type(e).__name__}: {e}' for e in errors]
        stage['elapsed_ms'] = (monotonic()-control.arrived_at)*1000
        persist(report)
        if errors:
            stage['status'] = 'failed'
            persist(report)
            raise RuntimeError(stage['cleanup_errors'])


def verify_real_sources(config, report):
    root = Path(config.goldenshare_lake_root)
    paths = dict(day=root/'silver/quote/stock_daily/trade_date=2026-10-15/part-000.parquet',
        factor=root/'silver/quote/adj_factor/trade_date=2026-10-15/part-000.parquet',
        week=root/'silver/quote/stock_weekly/week_end=2026-10-16/part-000.parquet',
        month=root/'silver/quote/stock_monthly/month=2026-10/part-000.parquet')
    sizes = {name: path.stat().st_size for name, path in paths.items()}
    if sum(sizes.values()) > 32*1024*1024:
        raise ValueError('The four named real files exceed 32MiB')
    report['real_preflight'] = dict(paths={k:str(v) for k,v in paths.items()}, bytes=sizes)
    persist(report)
    source = LakeTechnicalIndicatorPriceSource(config)
    for period in ('day', 'week', 'month'):
        local = replace(config, batch_rows=3)
        control = ExecutionControl(arrived_at=monotonic(), config=local)
        report['control_objects'] += 1
        service = TechnicalIndicatorService(source=source, registry=None, config=local)
        connection = inputs = None
        item = dict(period=period, status='running')
        report['real_sources'].append(item)
        context = SourceReadContext(local)
        request = CalculationRequest('stock', '600000.SH', period, (CalculationInstance('price','price',{}),))
        history = HistoryRequirement(frozenset(('close','volume','amount')), 0, True, (), initial_null_rule='source')
        requirement = ReadRequirement(request, history, 3, None, None)
        contract = price_contract(request)
        physical, standard = source_projection(contract, history.fields, 'qfq')
        description = SourceDescription(contract.source_id, '1', contract.input_adjustment,
            'latest_available_factor' if period=='day' else 'latest_published_factor', None, None,
            'CNY', contract.volume_unit, contract.amount_unit, 'Asia/Shanghai', 'period_start',
            'explicit_one_file_acceptance', None, period!='day', contract.adjustment_paths,
            period=='day', (paths[period],), ((date(2026,10,15),paths['factor']),) if period=='day' else (),
            physical, standard)
        try:
            connection, executor = service._open_execution(control)
            target_rows = executor.scalar('SELECT count(*) FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=?',
                (str(paths[period]), request.ts_code))
            if not 0 < target_rows <= 3:
                raise ValueError('Real price target count is outside the approved 1..3 rows')
            if period == 'day':
                factor_rows = executor.scalar('SELECT count(*) FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=?',
                    (str(paths['factor']), request.ts_code))
                if not 0 < factor_rows <= 3:
                    raise ValueError('Real factor target count is outside the approved 1..3 rows')
                item['factor_target_rows'] = factor_rows
            item['target_rows_before_read'] = target_rows
            persist(report)
            source._inspect(paths[period], physical, contract.schema, control, context)
            inputs = PriceInputSession(executor, source, description, requirement, read_context=context)
            inputs.prepare()
            batch = inputs.next_batch()
            assert batch is not None and batch.new_row_count == target_rows
            actual = executor.scalar('SELECT struct_pack(n:=count(*),close:=first(close),volume:=first(volume),'
                'amount:=first(amount),as_of:=first(source_as_of)) FROM ti_price_window')
            assert actual['n']==1 and actual['close'] is not None
            if period == 'day':
                assert inputs.resolved_description().basis_date == date(2026,10,15)
                assert inputs.conversion_batches==1 and context.source_files==2
                raw = executor.scalar('SELECT close FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=? LIMIT 1',
                    (str(paths[period]),request.ts_code))
                assert abs(actual['close']-raw)<1e-12  # single-date factor/basis ratio equals one
                # Execute the actual hfq basis method as well, with an earlier
                # display cutoff; this scope is one factor file, not full history.
                probe_requirement = replace(requirement, request=replace(request, adjustment='hfq',end=date(2020,1,1)))
                probe = source.prepare_basis(executor, description, probe_requirement,
                    table_name='ti_basis_probe', read_context=context)
                assert probe.basis_date==date(2026,10,15)
                item['hfq_probe_basis_date'] = probe.basis_date
                executor.drop_table('ti_basis_probe')
            else:
                assert inputs.conversion_batches==0 and context.source_files==1
            inputs.retain_required_history()
            inputs.finish_batch()
            assert inputs.next_batch() is None
            item.update(status='passed', values=actual, unique_files=context.source_files,
                source_rows=context.source_rows, basis_date=inputs.resolved_description().basis_date,
                basis_value=inputs.resolved_description().basis_value,
                conversion_batches=inputs.conversion_batches, sql_steps=len(executor.statistics))
        finally:
            errors = service._close_execution(control,connection,inputs=inputs)
            item['cleanup_errors'] = [f'{type(e).__name__}: {e}' for e in errors]
            item['elapsed_ms'] = (monotonic()-control.arrived_at)*1000
            persist(report)
            if errors:
                item['status'] = 'failed'
                persist(report)
                raise RuntimeError(item['cleanup_errors'])


def main():
    import duckdb
    import pyarrow
    report = dict(status='running', versions=dict(duckdb=duckdb.__version__,pyarrow=pyarrow.__version__),
        real_sources=[], control_objects=0, new_parquet_files=0, initial_peak_bytes=peak_bytes(),
        limitation='D2 inputs only; no indicator algorithms, full history, API or D4 resource acceptance')
    persist(report)
    started = monotonic()
    try:
        rejected = inspect_fixture(WRONG_FIXTURE)
        try:
            validate_fixture(rejected)
        except ValueError as error:
            report['wrong_sample'] = dict(metadata=rejected, status='rejected_before_reader', error=str(error))
        else:
            raise AssertionError('The wrong sample must be rejected before data access')
        persist(report)
        config = KernelConfig.from_settings(Settings(_env_file=None,GOLDENSHARE_LAKE_ROOT='/Volumes/datasource/data_lake'))
        verify_fixture(config, report)
        verify_real_sources(config, report)
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}',
                      cause=str(error.__cause__) if error.__cause__ else None)
        raise
    finally:
        report['elapsed_ms'] = (monotonic()-started)*1000
        report['final_peak_bytes'] = peak_bytes()
        persist(report)
    print(json.dumps(report,ensure_ascii=False,indent=2,default=str))


if __name__=='__main__':
    main()
