"""Fixed Prod aggregate requests and strict, bounded source-freeze evidence."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    MoneyflowHistoryDateCount,
    build_moneyflow_history_plan,
    history_business_key_fields,
    history_schema,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_DATASETS,
    MONEYFLOW_HISTORY_MAX_BUFFER_BYTES,
    MONEYFLOW_HISTORY_MAX_DATE_FACTS,
    MONEYFLOW_HISTORY_MAX_DATES_PER_WINDOW,
    MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT,
    MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
    MoneyflowContractError,
    market_moneyflow_day,
)


@dataclass(frozen=True)
class MoneyflowHistoryMetadataRequest:
    dataset: str
    cutoff: str
    sql_path: Path
    selected_dates: tuple[str, ...] | None = None

    def sql(self) -> str:
        return moneyflow_history_metadata_sql(
            self.dataset, self.cutoff, selected_dates=self.selected_dates
        )


def validate_moneyflow_history_selected_dates(cutoff, selected_dates):
    """Exact immutable date intent; no sorting, expansion or implicit fallback."""
    market_moneyflow_day(cutoff)
    if selected_dates is None:
        return None
    if (
        type(selected_dates) is not tuple
        or not 0 < len(selected_dates) <= MONEYFLOW_HISTORY_MAX_DATES_PER_WINDOW
    ):
        raise MoneyflowContractError("history_sample_dates")
    for day in selected_dates:
        market_moneyflow_day(day)
        if day > cutoff:
            raise MoneyflowContractError("history_cutoff")
    if selected_dates != tuple(sorted(set(selected_dates))):
        raise MoneyflowContractError("history_sample_dates")
    return selected_dates


def moneyflow_history_metadata_sql(
    dataset: str, cutoff: str, *, selected_dates: tuple[str, ...] | None = None
) -> str:
    if dataset not in MONEYFLOW_HISTORY_DATASETS:
        raise MoneyflowContractError("history_metadata_dataset")
    selected_dates = validate_moneyflow_history_selected_dates(cutoff, selected_dates)
    columns = ",".join(f"'{c.name}'" for c in history_schema(dataset))
    keys = history_business_key_fields(dataset)
    identity = ",".join(f'"{key}"' for key in keys)
    invalid = " OR ".join(
        f'"{key}" IS NULL'
        if key == "trade_date"
        else f'("{key}" IS NULL OR btrim("{key}")=\'\')'
        for key in keys
    )
    scoped = dataset == "moneyflow_ind_dc"
    scope = '"content_type"' if scoped else "''::text"
    grouping = '"trade_date","content_type"' if scoped else '"trade_date"'
    maximum = MONEYFLOW_HISTORY_MAX_DATE_FACTS * (3 if scoped else 1)
    predicate = f"\"trade_date\" <= DATE '{cutoff}'"
    selected_json = ""
    if selected_dates is not None:
        dates_sql = ",".join(f"DATE '{day}'" for day in selected_dates)
        predicate = f'"trade_date" IN ({dates_sql})'
        maximum = len(selected_dates) * (3 if scoped else 1)
        values_sql = ",".join(f"'{day}'" for day in selected_dates)
        selected_json = f"'selected_dates',json_build_array({values_sql}),"
    # Hex transports one small control JSON through COPY TEXT without CSV field
    # limits or COPY backslash/newline ambiguities. It contains no business rows.
    return (
        "BEGIN READ ONLY;\n"
        f"SET LOCAL statement_timeout = '{MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS}s';\n"
        "COPY (WITH facts AS (SELECT to_char(\"trade_date\",'YYYY-MM-DD') AS trade_date,"
        f"{scope} AS scope,count(*) AS rows,count(DISTINCT ({identity})) AS keys,"
        f"count(*) FILTER (WHERE {invalid}) AS invalid_keys FROM raw_tushare.{dataset} "
        f'WHERE ({predicate} OR "trade_date" IS NULL) '
        f'GROUP BY {grouping} ORDER BY "trade_date",{scope} COLLATE "C" LIMIT {maximum + 1}),'
        "cols AS (SELECT a.attname AS name,format_type(a.atttypid,a.atttypmod) AS type,"
        f"array_position(ARRAY[{columns}],a.attname::text) AS position "
        "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        f"WHERE n.nspname='raw_tushare' AND c.relname='{dataset}' "
        f"AND a.attnum>0 AND NOT a.attisdropped AND a.attname IN ({columns})) "
        "SELECT encode(convert_to(json_build_object("
        f"'dataset','{dataset}','cutoff','{cutoff}','relation_kind',"
        "(SELECT c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        f"WHERE n.nspname='raw_tushare' AND c.relname='{dataset}'),"
        f"{selected_json}"
        "'columns',coalesce((SELECT json_agg(json_build_array(name,type) ORDER BY position) FROM cols),'[]'::json),"
        "'facts',coalesce((SELECT json_agg(row_to_json(facts) ORDER BY trade_date,scope COLLATE \"C\") FROM facts),'[]'::json)"
        ")::text,'UTF8'),'hex')) TO STDOUT WITH (FORMAT TEXT);\n"
        "ROLLBACK;\n"
    )


def parse_moneyflow_history_metadata(
    wire: bytes, dataset: str, cutoff: str, *, selected_dates=None
) -> dict:
    if not isinstance(wire, bytes) or len(wire) > MONEYFLOW_HISTORY_MAX_BUFFER_BYTES:
        raise MoneyflowContractError("history_metadata_bytes")
    try:
        # Exactly one hex record, no commands, extra records or arbitrary text.
        value = wire.removesuffix(b"\n")
        if not value or re.fullmatch(b"[0-9a-f]+", value) is None:
            raise ValueError("metadata_record")
        result = json.loads(bytes.fromhex(value.decode("ascii")))
    except (ValueError, UnicodeError) as error:
        raise MoneyflowContractError("history_metadata_invalid") from error
    validate_moneyflow_history_metadata(
        result, dataset, cutoff, selected_dates=selected_dates
    )
    return result


def validate_moneyflow_history_metadata(
    value, dataset: str, cutoff: str, *, selected_dates=None
):
    """Return a current pure plan, retaining exact source types and DC scopes."""
    if dataset not in MONEYFLOW_HISTORY_DATASETS:
        raise MoneyflowContractError("history_metadata_dataset")
    selected_dates = validate_moneyflow_history_selected_dates(cutoff, selected_dates)
    fields = {"dataset", "cutoff", "relation_kind", "columns", "facts"}
    if selected_dates is not None:
        fields.add("selected_dates")
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or value["dataset"] != dataset
        or value["cutoff"] != cutoff
    ):
        raise MoneyflowContractError("history_metadata_identity")
    if selected_dates is not None and value["selected_dates"] != list(selected_dates):
        raise MoneyflowContractError("history_sample_identity")
    if value["relation_kind"] != "r":
        raise MoneyflowContractError("history_metadata_relation")
    columns = value["columns"]
    schema = history_schema(dataset)
    if not isinstance(columns, list) or len(columns) != len(schema):
        raise MoneyflowContractError("history_metadata_columns")
    for column, actual in zip(schema, columns, strict=True):
        if not isinstance(actual, list) or len(actual) != 2 or actual[0] != column.name:
            raise MoneyflowContractError("history_metadata_columns")
        source_type = actual[1]
        expected = (
            "date"
            if column.name == "trade_date"
            else column.type.lower().replace("decimal", "numeric")
        )
        valid = (
            isinstance(source_type, str)
            and (
                source_type == "text"
                or re.fullmatch(r"character varying(?:\([1-9][0-9]*\))?", source_type)
            )
            if expected == "varchar"
            else source_type == expected
        )
        if not valid:
            raise MoneyflowContractError("history_metadata_type:" + column.name)
    facts = value["facts"]
    scoped = dataset == "moneyflow_ind_dc"
    maximum_dates = (
        MONEYFLOW_HISTORY_MAX_DATE_FACTS
        if selected_dates is None
        else len(selected_dates)
    )
    if not isinstance(facts, list) or not 0 < len(facts) <= maximum_dates * (
        3 if scoped else 1
    ):
        raise MoneyflowContractError("history_metadata_fact_budget")
    dates, seen = {}, set()
    for fact in facts:
        if not isinstance(fact, dict) or set(fact) != {
            "trade_date",
            "scope",
            "rows",
            "keys",
            "invalid_keys",
        }:
            raise MoneyflowContractError("history_metadata_fact")
        day = market_moneyflow_day(fact["trade_date"])
        if day > cutoff:
            raise MoneyflowContractError("history_cutoff")
        if selected_dates is not None and day not in selected_dates:
            raise MoneyflowContractError("history_sample_outside_dates")
        scope = fact["scope"]
        if scope not in (("行业", "概念", "地域") if scoped else ("",)):
            raise MoneyflowContractError("history_metadata_scope")
        if (day, scope) in seen:
            raise MoneyflowContractError("history_metadata_duplicate")
        seen.add((day, scope))
        if any(
            type(fact[k]) is not int for k in ("rows", "keys", "invalid_keys")
        ) or not (
            fact["rows"] > 0
            and fact["keys"] == fact["rows"]
            and fact["invalid_keys"] == 0
        ):
            raise MoneyflowContractError("history_count_or_keys")
        rows, keys = dates.get(day, (0, 0))
        dates[day] = rows + fact["rows"], keys + fact["keys"]
    if len(dates) > MONEYFLOW_HISTORY_MAX_DATE_FACTS:
        raise MoneyflowContractError("history_date_fact_budget")
    if facts != sorted(facts, key=lambda f: (f["trade_date"], f["scope"])):
        raise MoneyflowContractError("history_metadata_order")
    plan = build_moneyflow_history_plan(
        dataset,
        (
            MoneyflowHistoryDateCount(day, rows, keys)
            for day, (rows, keys) in dates.items()
        ),
        cutoff=cutoff,
    )
    if (
        selected_dates is not None
        and plan.row_count > MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT
    ):
        raise MoneyflowContractError("history_sample_rows")
    return plan


def expected_history_scopes(snapshot: dict, dates) -> list:
    if snapshot["dataset"] != "moneyflow_ind_dc":
        return []
    return [
        [f["trade_date"], f["scope"], f["rows"]]
        for f in snapshot["facts"]
        if f["trade_date"] in dates
    ]
