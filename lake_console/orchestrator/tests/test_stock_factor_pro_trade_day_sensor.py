from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import dagster as dg
import pytest

from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.sensors import stock_factor_pro_trade_day_sensor as definition
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_dagster_events import _isolated_instance

TODAY = "2026-10-19"
PREVIOUS = "2026-10-16"
OLDER = "2026-10-15"
REGISTERED = "2026-10-14"
PARTITIONS = "cn_a_stock_factor_pro_trade_days"


@pytest.mark.parametrize(
    ("today_open", "previous_open", "has_file", "expected"),
    [
        pytest.param(True, True, True, [PREVIOUS, TODAY], id="open-day"),
        pytest.param(False, True, True, [PREVIOUS], id="closed-day"),
        pytest.param(None, True, True, [], id="missing-today"),
        pytest.param(True, True, False, [], id="missing-calendar"),
        pytest.param(True, None, True, [TODAY], id="missing-previous"),
        pytest.param(True, False, True, [TODAY], id="previous-closed"),
        pytest.param(False, None, True, [], id="closed-day-and-missing-previous"),
    ],
)
def test_registration_only_reads_calendar_and_candidate_keys(
    tmp_path, monkeypatch, today_open, previous_open, has_file, expected
):
    class ShanghaiClock(datetime):
        @classmethod
        def now(cls, tz):
            assert tz.key == "Asia/Shanghai"
            return cls(2026, 10, 19, 8, tzinfo=tz)

    monkeypatch.setattr(definition, "datetime", ShanghaiClock)
    lake = tmp_path / "lake"
    calendar = silver_trade_calendar_path(lake)
    if has_file:
        calendar.parent.mkdir(parents=True)
        # Silver calendar producer schema and a synthetic weekend boundary.
        # SZSE-only today and tomorrow must never substitute for SSE today.
        rows = [
            ("SSE", OLDER, True, REGISTERED),
            ("SSE", "2026-10-18", False, PREVIOUS),
            ("SZSE", TODAY, True, PREVIOUS),
            ("SSE", "2026-10-20", True, TODAY),
        ]
        if previous_open is not None:
            rows.append(("SSE", PREVIOUS, previous_open, OLDER))
        if today_open is not None:
            rows.append(("SSE", TODAY, today_open, PREVIOUS))
        with connection(tmp_path) as conn:
            conn.execute(
                "CREATE TABLE calendar (exchange VARCHAR, trade_date DATE, "
                "is_open BOOLEAN, pretrade_date DATE)"
            )
            conn.executemany("INSERT INTO calendar VALUES (?, ?, ?, ?)", rows)
            conn.execute("COPY calendar TO ? (FORMAT PARQUET)", [str(calendar)])

    queries = []

    class IsolatedDuckDB(DuckDBResource):
        @contextmanager
        def connect(self):
            with connection(tmp_path) as conn:

                def execute(sql, parameters):
                    queries.append(sql)
                    return conn.execute(sql, parameters)

                yield SimpleNamespace(execute=execute)

    sensor = definition.stock_factor_pro_trade_day_sensor
    assert sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert sensor.minimum_interval_seconds == 600
    assert sensor.tags == {
        "goldenshare/sensor_domain": "quote_data",
        "goldenshare/sensor_target_layer": "partition",
        "goldenshare/sensor_role": "partition_registration",
    }
    with _isolated_instance(tmp_path) as instance:
        instance.add_dynamic_partitions(PARTITIONS, [REGISTERED])

        def evaluate():
            with dg.build_sensor_context(
                instance=instance,
                resources={
                    "lake_root": LakeRootResource(root_path=str(lake)),
                    "duckdb": IsolatedDuckDB(),
                },
            ) as context:
                with patch.object(
                    instance,
                    "has_dynamic_partition",
                    wraps=instance.has_dynamic_partition,
                ) as lookup:
                    result = sensor.evaluate_tick(context)
                assert [
                    c.kwargs["partition_key"] for c in lookup.call_args_list
                ] == expected
            assert not result.run_requests
            return result

        result = evaluate()
        assert instance.get_dynamic_partitions(PARTITIONS) == [REGISTERED]
        if expected:
            (request,) = result.dynamic_partitions_requests
            assert request.partitions_def_name == PARTITIONS
            assert request.partition_keys == expected
            instance.add_dynamic_partitions(PARTITIONS, request.partition_keys)
            assert not evaluate().dynamic_partitions_requests
            assert len(queries) == 2
        else:
            assert result.skip_message
            assert not result.dynamic_partitions_requests
            assert len(queries) == 1
        assert set(instance.get_dynamic_partitions(PARTITIONS)) == {
            REGISTERED,
            *expected,
        }
