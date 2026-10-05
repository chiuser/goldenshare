"""Open existing local PG stores with all automatic table creation disabled."""

from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path

import dagster as dg
import yaml
from dagster._config import process_config
from dagster._core.instance.ref import InstanceRef
from dagster._core.instance.types import InstanceType
from dagster._core.storage.config import pg_config
from dagster._core.storage.root import LocalArtifactStorage
from dagster._serdes import ConfigurableClassData
from dagster_postgres import (
    PostgresEventLogStorage,
    PostgresRunStorage,
)
from dagster_postgres.utils import pg_url_from_config
from sqlalchemy.engine import make_url

from orchestrator.defs.anns_d_checkpoint import assert_safe_announcement_path
from orchestrator.defs.anns_d_contract import AnnouncementError

INSTANCE_HOME = Path("/Users/congming/.goldenshare/dagster_home")


def _configuration(home):
    home = Path(home)
    if home != INSTANCE_HOME:
        raise AnnouncementError("instance_home_mismatch")
    path = home / "dagster.yaml"
    assert_safe_announcement_path(path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise AnnouncementError("instance_config_missing_or_large")
    payload = path.read_bytes()
    config = yaml.safe_load(payload)
    if (
        type(config) is not dict
        or "instance_class" in config
        or any(
            k in config
            for k in ("run_storage", "event_log_storage", "schedule_storage")
        )
        or type(config.get("storage")) is not dict
        or set(config["storage"]) != {"postgres"}
    ):
        raise AnnouncementError("unsupported_instance_configuration")
    pg = config["storage"]["postgres"]
    if type(pg) is not dict or "auth" in pg:
        raise AnnouncementError("unsupported_instance_storage")
    result = process_config(pg_config(), pg)
    if not result.success:
        raise AnnouncementError("invalid_instance_storage_config")
    url = pg_url_from_config(result.value)
    parsed = make_url(url)
    if (
        parsed.drivername not in ("postgresql", "postgresql+psycopg2")
        or parsed.host not in ("localhost", "127.0.0.1", "::1")
        or parsed.query
        or parsed.database != "goldenshare_dagster"
        or not parsed.username
    ):
        raise AnnouncementError("unsupported_instance_storage")
    artifact = config.get("local_artifact_storage")
    if (
        type(artifact) is not dict
        or artifact.get("module")
        not in ("dagster.core.storage.root", "dagster._core.storage.root")
        or artifact.get("class") != "LocalArtifactStorage"
        or type(artifact.get("config")) is not dict
        or set(artifact["config"]) != {"base_dir"}
    ):
        raise AnnouncementError("unsupported_instance_artifact_storage")
    root = Path(artifact["config"]["base_dir"])
    assert_safe_announcement_path(root)
    if not root.is_dir():
        raise AnnouncementError("instance_artifact_directory_missing")
    identity = {
        "home": str(home),
        "config_sha256": sha256(payload).hexdigest(),
        "artifact_root": str(root),
        "storage": {
            "host": parsed.host,
            "port": parsed.port or 5432,
            "database": parsed.database,
            "username": parsed.username,
        },
    }
    return url, root, identity


@contextmanager
def open_announcement_event_instance(*, identity=None, writable=False):
    """No default discovery, initialization, DDL, launcher or config mutations."""
    url, root, actual = _configuration(INSTANCE_HOME)
    if identity is not None and identity != actual:
        raise AnnouncementError("instance_identity_changed")
    url = (
        make_url(url)
        .update_query_dict(
            {
                "options": "-c statement_timeout=10000"
                + ("" if writable else " -c default_transaction_read_only=on")
            }
        )
        .render_as_string(hide_password=False)
    )
    ref = InstanceRef(
        local_artifact_storage_data=ConfigurableClassData(
            "dagster._core.storage.root",
            "LocalArtifactStorage",
            yaml.safe_dump({"base_dir": str(root)}),
        ),
        compute_logs_data=ConfigurableClassData(
            "dagster._core.storage.noop_compute_log_manager",
            "NoOpComputeLogManager",
            "{}",
        ),
        scheduler_data=None,
        run_coordinator_data=None,
        run_launcher_data=None,
        settings={"telemetry": {"enabled": False}},
        run_storage_data=None,
        event_storage_data=None,
        schedule_storage_data=None,
    )
    with ExitStack() as stack:
        stores = []
        for kind in (
            PostgresRunStorage,
            PostgresEventLogStorage,
        ):
            store = kind(url, should_autocreate_tables=False)
            stack.callback(store.dispose)
            stores.append(store)
        instance = dg.DagsterInstance(
            instance_type=InstanceType.PERSISTENT,
            local_artifact_storage=LocalArtifactStorage(str(root)),
            run_storage=stores[0],
            event_storage=stores[1],
            schedule_storage=None,
            compute_log_manager=None,
            run_coordinator=None,
            run_launcher=None,
            settings={"telemetry": {"enabled": False}},
            ref=ref,
        )
        if _configuration(INSTANCE_HOME)[2] != actual:
            raise AnnouncementError("instance_identity_changed")
        yield instance, actual
