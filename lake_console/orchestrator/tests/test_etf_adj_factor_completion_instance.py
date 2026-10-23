"""Real helper/SDK execution, replacing only PG storage with temporary SQLite.

LLD 11.9.18 records the independently observed formal descriptor: an empty
QueuedRunCoordinator config and runs=1/pools=run. These literal inputs and
expected values do not come from the helper. The six small checks exercise
instance execution and target binding, not the ETF file quality rules. SQLite
creates its own temporary test tables; this is not evidence of PG performance
or permission to initialize formal PostgreSQL.
"""

from copy import deepcopy
from types import SimpleNamespace

import dagster as dg
import pytest
import yaml
from dagster._core.events import DagsterEventType
from dagster._core.launcher.default_run_launcher import DefaultRunLauncher
from dagster._core.run_coordinator.queued_run_coordinator import QueuedRunCoordinator
from dagster._core.storage.event_log.sqlite import SqliteEventLogStorage
from dagster._core.storage.runs.sqlite import SqliteRunStorage
from sqlalchemy.engine import make_url

from orchestrator.defs.bootstrap import daily_basic_event_instance as helper
from orchestrator.defs.daily_basic_contract import DailyBasicValidationError

ASSET = "silver_etf_adj_factor"
DAY = "2026-09-03"
CHECK_NAMES = ("file", "schema", "keys", "source", "values", "coverage")
CONCURRENCY = {
    "runs": {"max_concurrent_runs": 1},
    "pools": {"granularity": "run"},
}


def forbidden(*_args, **_kwargs):
    pytest.fail("unexpected storage rehydration, launcher, submission or writer")


@pytest.fixture
def controlled_instance(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    config = {
        "storage": {
            "postgres": {
                "postgres_url": "postgresql://fixture:unused@localhost/goldenshare_dagster"
            }
        },
        "local_artifact_storage": {
            "module": "dagster._core.storage.root",
            "class": "LocalArtifactStorage",
            "config": {"base_dir": str(artifact)},
        },
        "run_coordinator": {
            "module": "dagster._core.run_coordinator",
            "class": "QueuedRunCoordinator",
            "config": {},
        },
        "concurrency": deepcopy(CONCURRENCY),
        # Deliberately different extras: copying all settings would require a
        # launcher here and would violate the approved maintenance boundary.
        "telemetry": {"enabled": True},
        "run_monitoring": {"enabled": True, "max_resume_run_attempts": 1},
    }
    config_path = home / "dagster.yaml"
    config_path.write_text(yaml.safe_dump(config))
    original_config = config_path.read_bytes()
    constructors = []

    def event_storage(url, *, should_autocreate_tables):
        assert should_autocreate_tables is False
        constructors.append(("event", url, should_autocreate_tables))
        return SqliteEventLogStorage(str(tmp_path / "events"))

    def run_storage(url, *, should_autocreate_tables):
        assert should_autocreate_tables is False
        constructors.append(("run", url, should_autocreate_tables))
        return SqliteRunStorage.from_local(str(tmp_path / "runs"))

    monkeypatch.setattr(helper, "INSTANCE_HOME", home)
    monkeypatch.setattr(helper, "PostgresEventLogStorage", event_storage)
    monkeypatch.setattr(helper, "PostgresRunStorage", run_storage)
    monkeypatch.setattr(helper.InstanceRef, "storage", property(forbidden))
    monkeypatch.setattr(helper.InstanceRef, "run_launcher", property(forbidden))
    monkeypatch.setattr(QueuedRunCoordinator, "submit_run", forbidden)
    monkeypatch.setattr(DefaultRunLauncher, "launch_run", forbidden)
    yield SimpleNamespace(
        constructors=constructors, config=config, config_path=config_path, home=home
    )
    assert config_path.read_bytes() == original_config
    for _kind, url, autocreate in constructors:
        parsed = make_url(url)
        assert parsed.host == "localhost" and parsed.database == "goldenshare_dagster"
        assert autocreate is False
        assert "statement_timeout=10000" in parsed.query["options"]


def check_job(observed):
    partitions = dg.StaticPartitionsDefinition([DAY])

    @dg.asset(name=ASSET, partitions_def=partitions)
    def target():
        forbidden()

    @dg.multi_asset_check(
        specs=[
            dg.AssetCheckSpec(
                name=name, asset=target, blocking=True, partitions_def=partitions
            )
            for name in CHECK_NAMES
        ],
    )
    def checks():
        observed.append("checks_executed")
        for name in CHECK_NAMES:
            yield dg.AssetCheckResult(
                passed=True,
                asset_key=ASSET,
                check_name=name,
                severity=dg.AssetCheckSeverity.ERROR,
            )

    definitions = dg.Definitions(
        assets=[target],
        asset_checks=[checks],
        jobs=[
            dg.define_asset_job(
                "instance_checks",
                selection=dg.AssetSelection.assets(target),
                executor_def=dg.in_process_executor,
            )
        ],
    )
    return definitions.resolve_job_def("instance_checks").get_subset(
        asset_selection=set(), asset_check_selection=set(checks.check_keys)
    )


def materialization(instance):
    instance.report_runless_asset_event(
        dg.AssetMaterialization(asset_key=ASSET, partition=DAY)
    )
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=dg.AssetKey(ASSET), asset_partitions=[DAY]),
        limit=1,
    ).records
    assert len(records) == 1
    return records[0].storage_id


def test_original_instance_reproduces_missing_coordinator_before_checks(
    controlled_instance,
):
    observed = []
    with helper.daily_basic_event_instance(writable=True) as instance:
        target_id = materialization(instance)
        result = check_job(observed).execute_in_process(
            instance=instance, partition_key=DAY, raise_on_error=False
        )
        assert result.success is False
        assert observed == [] and result.get_asset_check_evaluations() == []
        assert not any(
            event.event_type is DagsterEventType.STEP_START
            for event in result.all_events
        )
        assert "Run coordinator not configured in instance ref" in "\n".join(
            str(getattr(event.event_specific_data, "error", ""))
            for event in result.all_events
        )
        assert (
            instance.get_run_by_id(result.run_id).status is dg.DagsterRunStatus.FAILURE
        )
        assert (
            instance.fetch_materializations(dg.AssetKey(ASSET), limit=1)
            .records[0]
            .storage_id
            == target_id
        )


def test_execution_preserves_actual_config_and_saves_six_bound_results(
    controlled_instance,
):
    observed = []
    with helper.daily_basic_event_instance(
        writable=True, for_execution=True
    ) as instance:
        reference = instance.get_ref()
        assert reference.settings == {
            "telemetry": {"enabled": False},
            "concurrency": {
                "runs": {"max_concurrent_runs": 1},
                "pools": {"granularity": "run"},
            },
        }
        assert instance.get_settings("concurrency") == CONCURRENCY
        assert instance.get_settings("run_monitoring") == {}
        assert reference.run_launcher_data is None and reference.scheduler_data is None
        assert reference.storage_data is None
        assert reference.run_coordinator_data.class_name == "QueuedRunCoordinator"
        assert yaml.safe_load(reference.run_coordinator_data.config_yaml) == {}
        assert isinstance(instance.run_coordinator, QueuedRunCoordinator)
        concurrency = instance.get_concurrency_config()
        assert concurrency.run_queue_config.max_concurrent_runs == 1
        assert concurrency.pool_config.pool_granularity.value == "run"
        assert instance.event_log_storage.get_pool_config() == concurrency.pool_config
        target_id = materialization(instance)
        result = check_job(observed).execute_in_process(
            instance=instance, partition_key=DAY, raise_on_error=False
        )
        assert result.success and observed == ["checks_executed"]
        evaluations = result.get_asset_check_evaluations()
        assert len(evaluations) == 6
        assert {evaluation.check_name for evaluation in evaluations} == set(CHECK_NAMES)
        for evaluation in evaluations:
            assert evaluation.passed and evaluation.blocking
            assert evaluation.severity is dg.AssetCheckSeverity.ERROR
            assert evaluation.asset_key == dg.AssetKey(ASSET)
            assert evaluation.partition == DAY
            assert evaluation.target_materialization_data.storage_id == target_id
        saved = instance.get_records_for_run(
            result.run_id, of_type=DagsterEventType.ASSET_CHECK_EVALUATION, limit=7
        )
        assert not saved.has_more and len(saved.records) == 6
        assert {
            record.event_log_entry.asset_check_evaluation.check_name
            for record in saved.records
        } == set(CHECK_NAMES)
        assert all(
            record.event_log_entry.asset_check_evaluation.target_materialization_data.storage_id
            == target_id
            for record in saved.records
        )
        assert (
            instance.get_run_by_id(result.run_id).status is dg.DagsterRunStatus.SUCCESS
        )
    assert len(controlled_instance.constructors) == 2
    assert all(
        "default_transaction_read_only" not in url
        for _, url, _ in controlled_instance.constructors
    )


@pytest.mark.parametrize("writable", [False, True])
def test_default_read_and_runless_never_parse_execution_config(
    controlled_instance, monkeypatch, writable
):
    monkeypatch.setattr(helper.InstanceRef, "from_dir", forbidden)
    with helper.daily_basic_event_instance(writable=writable) as instance:
        assert instance.get_ref().run_coordinator_data is None
        assert instance.get_ref().settings == {"telemetry": {"enabled": False}}
        if writable:
            materialization(instance)
        else:
            assert (
                instance.fetch_materializations(dg.AssetKey(ASSET), limit=1).records
                == []
            )
    for _, url, _ in controlled_instance.constructors:
        assert ("default_transaction_read_only" in url) is (not writable)


def test_readonly_execution_is_rejected_before_config_or_storage(monkeypatch):
    monkeypatch.setattr(helper, "INSTANCE_HOME", None)
    monkeypatch.setattr(helper, "PostgresEventLogStorage", forbidden)
    monkeypatch.setattr(helper, "PostgresRunStorage", forbidden)
    with (
        pytest.raises(DailyBasicValidationError, match="execution_requires_writable"),
        helper.daily_basic_event_instance(for_execution=True),
    ):
        pytest.fail("invalid instance was yielded")


def test_missing_execution_description_is_not_defaulted(
    controlled_instance, monkeypatch
):
    reference = helper.InstanceRef.from_dir(str(controlled_instance.home))
    reference = reference._replace(run_coordinator_data=None)
    monkeypatch.setattr(helper.InstanceRef, "from_dir", lambda _home: reference)
    with (
        pytest.raises(
            DailyBasicValidationError, match="execution_configuration_missing"
        ),
        helper.daily_basic_event_instance(writable=True, for_execution=True),
    ):
        pytest.fail("incomplete execution configuration was accepted")
    assert controlled_instance.constructors == []


def test_legitimate_missing_concurrency_keeps_sdk_defaults(controlled_instance):
    config = deepcopy(controlled_instance.config)
    del config["concurrency"]
    original = controlled_instance.config_path.read_bytes()
    controlled_instance.config_path.write_text(yaml.safe_dump(config))
    try:
        with helper.daily_basic_event_instance(
            writable=True, for_execution=True
        ) as instance:
            assert "concurrency" not in instance.get_ref().settings
            assert instance.get_settings("concurrency") == {}
            concurrency = instance.get_concurrency_config()
            # Independent SDK contract: QueuedRunCoordinator's empty component
            # config defaults to 10; no pool setting means no pool granularity.
            assert concurrency.run_queue_config.max_concurrent_runs == 10
            assert concurrency.pool_config.pool_granularity is None
            assert (
                instance.event_log_storage.get_pool_config() == concurrency.pool_config
            )
    finally:
        controlled_instance.config_path.write_bytes(original)


def test_invalid_formal_concurrency_is_rejected_before_storage(controlled_instance):
    config = deepcopy(controlled_instance.config)
    config["concurrency"]["pools"]["granularity"] = "unregistered_value"
    original = controlled_instance.config_path.read_bytes()
    controlled_instance.config_path.write_text(yaml.safe_dump(config))
    try:
        with (
            pytest.raises(dg.DagsterInvalidConfigError),
            helper.daily_basic_event_instance(writable=True, for_execution=True),
        ):
            pytest.fail("invalid formal configuration was accepted")
        assert controlled_instance.constructors == []
    finally:
        controlled_instance.config_path.write_bytes(original)
