"""Bounded query/file work, measured only on temporary fixtures."""

from datetime import date, timedelta
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import Mock, patch

import dagster as dg

from orchestrator.defs.asset_guards.daily_basic_readiness import (
    batch_daily_basic_readiness,
)
from orchestrator.defs.daily_basic_contract import DAILY_BASIC_ASSET
from tests.test_daily_basic_raw_io import DB, Source, row, write

GUARD = "orchestrator.defs.asset_guards.daily_basic_readiness"


def test_ten_day_bounded_fixture(tmp_path, capsys):
    days = [(date(2026, 9, 1) + timedelta(days=i)).isoformat() for i in range(10)]
    records = []
    for i, day in enumerate(days):
        data = [row(str(n), trade_date=day.replace("-", "")) for n in range(1000)]
        evidence = write(
            tmp_path,
            trade_date=day,
            tushare=Source(data),
            load_expected_codes=lambda: ["0"],
        )
        records.append(
            SimpleNamespace(
                partition_key=day,
                storage_id=i + 1,
                asset_materialization=dg.AssetMaterialization(
                    DAILY_BASIC_ASSET,
                    metadata={"goldenshare/" + k: v for k, v in evidence.items()},
                ),
            )
        )
    instance = Mock()
    instance.fetch_materializations.return_value = SimpleNamespace(records=records)

    def checks(instance, day):
        target = SimpleNamespace(storage_id=days.index(day) + 1)
        record = SimpleNamespace(
            status="SUCCEEDED",
            event=SimpleNamespace(
                dagster_event=SimpleNamespace(
                    event_specific_data=SimpleNamespace(
                        target_materialization_data=target
                    )
                )
            ),
        )
        return {"contract": record, "coverage": record}

    from orchestrator.defs.daily_basic_raw_io import audit_daily_basic_file

    with (
        DB().connect() as connection,
        patch(
            GUARD + ".current_daily_basic_check_records", side_effect=checks
        ) as check_query,
        patch(GUARD + ".load_daily_basic_input_codes", return_value=("0",)),
        patch(GUARD + ".audit_daily_basic_file", wraps=audit_daily_basic_file) as audit,
    ):
        started = perf_counter()
        result = batch_daily_basic_readiness(
            instance, connection, tmp_path / "lake", days
        )
        elapsed = perf_counter() - started
    assert all(s.ready for s in result.values())
    instance.fetch_materializations.assert_called_once()
    assert instance.fetch_materializations.call_args.kwargs["limit"] == 100
    assert check_query.call_count == 10
    assert audit.call_count == 10
    assert len({call.args[1] for call in audit.call_args_list}) == 10
    assert elapsed < 10
    with capsys.disabled():
        print(
            f"daily_basic_fixture: days=10 rows=10000 output_files=10 materialization_queries=1 check_batches=10 elapsed_seconds={elapsed:.3f}"
        )
