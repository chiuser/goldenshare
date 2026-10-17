"""Fixed scope and bounded control metadata, never business rows or credentials."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.run_contracts import moneyflow_automation as automation
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA,
    SILVER_MONEYFLOW_MKT_DC_SCHEMA,
)
from orchestrator.defs.run_contracts.moneyflow_daily import daily_schema


@dataclass(frozen=True)
class ContinuationPolicy:
    source_files: int = 3000
    dependency_files: int = 1000
    control_entries_per_action: int = 8
    max_units: int = 49
    dates_per_read: int = 10
    plan_reads: int = 400
    plan_seconds: int = 300
    transition_reads: int = 40
    transitions_per_unit: int = 5
    run_reads: int = 120
    run_seconds: int = 1200
    poll_seconds: int = 10
    run_query_limit: int = 3
    plan_bytes: int = 4 * 1024**2
    action_bytes: int = 64 * 1024
    control_bytes: int = 16 * 1024**2
    rss_bytes: int = 768 * 1024**2
    disk_bytes: int = 32 * 1024**3
    free_bytes: int = 64 * 1024**3
    files_per_run: int = 512
    depth_per_run: int = 8
    raw_activity_seconds: int = 4 * 60 * 60


POLICY = ContinuationPolicy()
DATASETS = (
    "moneyflow_mkt_dc",
    "moneyflow_ind_ths",
    "moneyflow_cnt_ths",
    "moneyflow_ind_dc",
    "moneyflow_dc",
    "moneyflow_ths",
    "moneyflow",
)
CONTRACTS = {
    value.dataset: value
    for value in vars(automation).values()
    if isinstance(value, automation.MoneyflowAutomationContract)
}
REPOSITORY = {
    "repositoryLocationName": "orchestrator",
    "repositoryName": "__repository__",
}
ENDPOINT = "http://127.0.0.1:3000/graphql"
PROJECT = Path(__file__).resolve().parents[3]
REPO = PROJECT.parents[1]
CONTROL = Path("/Volumes/datasource/data_lake_staging/moneyflow/continuation")
ACTIVE = frozenset({"QUEUED", "NOT_STARTED", "STARTING", "STARTED", "CANCELING"})


class ContinuationError(Exception):
    def __init__(self, reason, code=3):
        self.reason, self.code = reason, code
        super().__init__(reason)


def require(condition, reason, code=3):
    if not condition:
        raise ContinuationError(reason, code)


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def encoded(value):
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def safe_path(path):
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "unsafe_path", 2)
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink", 2)
    return path


def file_hash(path):
    path = safe_path(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path, limit=POLICY.plan_bytes):
    path = safe_path(path)
    require(path.is_file() and path.stat().st_size <= limit, "control_file_size", 2)
    try:
        value = json.loads(path.read_bytes())
    except (ValueError, UnicodeError) as error:
        raise ContinuationError("invalid_json", 2) from error
    require(isinstance(value, dict), "json_object_required", 2)
    return value


def schema(dataset, silver=False):
    if dataset == "moneyflow_mkt_dc":
        return (
            SILVER_MONEYFLOW_MKT_DC_SCHEMA
            if silver
            else RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA
        )
    return daily_schema(dataset, silver=silver)


def unit_identity(dataset, day):
    from orchestrator.defs.paths import (
        DEFAULT_LAKE_ROOT,
        raw_moneyflow_path,
        silver_moneyflow_path,
    )

    contract = CONTRACTS[dataset]
    return {
        "dataset": dataset,
        "trade_date": day,
        "partition_set": contract.partition_set,
        **{
            layer: {
                "asset": getattr(contract, layer + "_asset"),
                "job": getattr(contract, layer + "_job"),
                "check": getattr(contract, layer + "_check"),
                "schema": [
                    [c.name, c.type] for c in schema(dataset, layer == "silver")
                ],
                "target": str(
                    (raw_moneyflow_path if layer == "raw" else silver_moneyflow_path)(
                        Path(DEFAULT_LAKE_ROOT), dataset, day
                    )
                ),
            }
            for layer in ("raw", "silver")
        },
    }


def policy_dict():
    return asdict(POLICY)
