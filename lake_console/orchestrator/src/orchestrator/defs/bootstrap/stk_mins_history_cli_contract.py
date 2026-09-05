"""Shared parsing only; this module never discovers files or writes data/events."""

from __future__ import annotations

import argparse

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days


def add_history_selection_arguments(
    parser: argparse.ArgumentParser, *, default_start_date: str
) -> None:
    parser.add_argument("--start-date", default=default_start_date)
    parser.add_argument("--end-date")
    parser.add_argument("--partition-keys")
    parser.add_argument("--freqs")
    parser.add_argument("--years")


def parse_optional_partition_keys(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    return tuple(sorted(key.strip() for key in value.split(",") if key.strip()))


def parse_optional_csv_values(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    return tuple(item.strip() for item in value.split(",") if item.strip())


def registered_stk_mins_silver_partition_keys(
    instance: dg.DagsterInstance | None = None,
) -> tuple[str, ...]:
    selected_instance = instance if instance is not None else dg.DagsterInstance.get()
    return tuple(
        sorted(
            selected_instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
