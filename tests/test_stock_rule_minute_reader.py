"""Temporary Parquet source, never a write to the formal Lake."""
from datetime import date
from pathlib import Path
from decimal import Decimal

import pytest

pytest.importorskip("duckdb")
from tests.test_stock_mins_reader import _write_bars
from src.foundation.clients.local_lake.stock_rule_minute_reader import StockRuleMinuteReader
from src.foundation.clients.local_lake.stock_mins_reader import MinuteSourceContractError, MinuteQueryError
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, DeadlineExceeded


DAY = date(2026, 7, 31)


def row(time, price=10.123456789, volume=0):
    return ("000638.SZ", 1, DAY, "2026-07-31 " + time, price, price, price, price, volume, 0, "SZSE")


def read(root, **options):
    return StockRuleMinuteReader(root).read_day(stock_code="000638.SZ", trade_date=DAY,
        **(dict(row_limit=500, byte_limit=1048576, remaining_ms=Deadline.after_ms(2000).remaining_ms) | options))


def test_exact_source_precision_order_zero_and_reproducible_material(tmp_path):
    _write_bars(tmp_path, freq=1, rows=[row("09:32:00", volume=123), row("09:30:00"), row("09:31:00")])
    first = read(tmp_path)
    second = read(tmp_path)
    assert [r.checkpoint_at.minute for r in first.rows] == [30, 31, 32]
    assert Decimal(first.rows[0].close_text) == Decimal("10.123456789")
    assert Decimal(first.rows[0].volume_shares_text) == 0
    assert first.source_version == second.source_version and first.scanned_files == 1
    assert first.payload_bytes < 1048576 and first.elapsed_ms < 2000
    assert first.rows[0].checkpoint_at.isoformat().endswith("+08:00")


@pytest.mark.parametrize("rows", [[row("09:31:00"), row("09:31:00")], [row("09:31:01")]])
def test_duplicate_and_nonminute_identity_rejected(tmp_path, rows):
    _write_bars(tmp_path, freq=1, rows=rows)
    with pytest.raises(MinuteSourceContractError):
        read(tmp_path)


@pytest.mark.parametrize("options", [dict(row_limit=1), dict(byte_limit=1)])
def test_bounded_material_rejected_not_truncated(tmp_path, options):
    _write_bars(tmp_path, freq=1, rows=[row("09:31:00"), row("09:32:00")])
    with pytest.raises(MinuteSourceContractError):
        read(tmp_path, **options)


def test_missing_source_and_expired_deadline(tmp_path):
    with pytest.raises(MinuteQueryError):
        read(tmp_path)
    def expired():
        raise DeadlineExceeded("expired")
    with pytest.raises(DeadlineExceeded):
        read(tmp_path, remaining_ms=expired)


def test_source_replacement_during_read_is_not_silently_frozen(tmp_path, monkeypatch):
    target = _write_bars(tmp_path, freq=1, rows=[row("09:31:00")])
    original = Path.stat
    observed = [0]
    def changed(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == target:
            observed[0] += 1
            if observed[0] >= 3:
                from types import SimpleNamespace
                return SimpleNamespace(st_dev=result.st_dev, st_ino=result.st_ino + 1,
                    st_size=result.st_size, st_mtime_ns=result.st_mtime_ns)
        return result
    monkeypatch.setattr(Path, "stat", changed)
    with pytest.raises(MinuteQueryError, match="版本发生变化"):
        read(tmp_path)
