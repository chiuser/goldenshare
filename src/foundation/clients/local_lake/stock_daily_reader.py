"""Read existing qfq stock daily prices once, then continue into older history."""

from datetime import date
from pathlib import Path

from goldenshare_technical_indicators.errors import SourceContractError, SourceReadError


_KLINE_FIELDS = (
    "ts_code", "trade_date", "open_qfq", "high_qfq", "low_qfq", "close_qfq",
    "pre_close", "change", "pct_chg", "vol", "amount", "turnover_rate", "volume_ratio",
)
_PREVIOUS_FIELDS = ("trade_date", "high_qfq", "low_qfq", "close_qfq")


class StockDailyLakeReader:
    """Request-owned forward cursor over reverse-ordered date partitions."""

    def __init__(self, config):
        self._config = config
        self._paths = None
        self._position = 0
        self._reader = None

    def _locate(self, end_date, check_active):
        if not self._config.goldenshare_lake_root:
            raise SourceContractError("Stock daily Lake root has not been configured")
        root = Path(self._config.goldenshare_lake_root).expanduser().resolve()
        for forbidden in (Path("/Volumes/datasource/data_lake_staging"),
                          Path("/Volumes/datasource/goldenshare-tushare-lake")):
            if root == forbidden or root.is_relative_to(forbidden):
                raise SourceContractError("Stock daily prices require a formal Lake root")
        base = root / "silver/stock_factor_pro"
        check_active()
        if not base.is_dir():
            raise SourceReadError("Stock daily technical factor directory is unavailable")
        paths = []
        for path in base.iterdir():
            check_active()
            if path.name.startswith("trade_date=") and path.is_dir():
                day = date.fromisoformat(path.name.removeprefix("trade_date="))
                if day <= end_date:
                    paths.append((day, path / "data.parquet"))
        self._paths = sorted(paths, reverse=True)

    def _scan(self, paths, ts_code, end_date, start_date, fields, check_active, *, exclusive_end):
        import pyarrow as pa
        import pyarrow.dataset as ds

        schema = pa.schema([
            (name, pa.string() if name == "ts_code" else
             pa.date32() if name == "trade_date" else pa.float64())
            for name in dict.fromkeys(("ts_code",) + fields)
        ])
        end_filter = (ds.field("trade_date") < end_date if exclusive_end
                      else ds.field("trade_date") <= end_date)
        predicate = (ds.field("ts_code") == ts_code) & end_filter
        if start_date is not None:
            predicate &= ds.field("trade_date") >= start_date
        check_active()
        dataset = ds.dataset([str(path) for path in paths], format="parquet", schema=schema)
        scanner = dataset.scanner(
            columns=list(fields), filter=predicate, batch_size=self._config.batch_rows,
            batch_readahead=0, fragment_readahead=0, use_threads=False,
            cache_metadata=False, fragment_scan_options=ds.ParquetFragmentScanOptions(pre_buffer=False),
        )
        check_active()
        self._reader = scanner.to_reader()
        try:
            rows = []
            for batch in self._reader:
                check_active()
                rows.extend(batch.to_pylist())
                check_active()
            return rows
        finally:
            self._reader.close()
            self._reader = None

    def _load(self, ts_code, end_date, start_date, limit, fields, check_active, *, exclusive_end=False):
        import pyarrow as pa

        try:
            if self._paths is None:
                self._locate(end_date, check_active)
            rows = []
            while len(rows) < limit and self._position < len(self._paths):
                check_active()
                paths = []
                remaining = min(limit - len(rows), self._config.batch_rows)
                while len(paths) < remaining and self._position < len(self._paths):
                    day, path = self._paths[self._position]
                    if start_date is not None and day < start_date:
                        break
                    self._position += 1
                    if day < end_date or (day == end_date and not exclusive_end):
                        paths.append(path)
                if not paths:
                    break
                rows.extend(self._scan(paths, ts_code, end_date, start_date, fields, check_active,
                                       exclusive_end=exclusive_end))
            check_active()
            rows.sort(key=lambda row: row["trade_date"])
            return rows
        except OSError as error:
            raise SourceReadError("Stock daily technical factor files could not be read") from error
        except pa.ArrowException as error:
            raise SourceContractError("Stock daily technical factor projection failed") from error

    def load_kline_rows(self, ts_code, end_date, start_date, limit, check_active):
        return self._load(ts_code, end_date, start_date, limit, _KLINE_FIELDS, check_active)

    def load_previous_kline_rows(self, ts_code, before, limit, check_active):
        # The cursor is already before the page; compare exact dates, not calendar offsets.
        return self._load(ts_code, before, None, limit, _PREVIOUS_FIELDS, check_active,
                          exclusive_end=True)

    def close(self):
        try:
            if self._reader is not None:
                self._reader.close()
        finally:
            self._reader = self._paths = None
