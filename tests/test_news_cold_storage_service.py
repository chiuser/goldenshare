from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.foundation.services.migration.news_cold_storage.models import (
    NewsColdStorageSummary,
    NewsColdStorageVerification,
)
from src.foundation.services.migration.news_cold_storage.service import NewsColdStorageMigrationService


def _summary(*, row_count: int = 2) -> NewsColdStorageSummary:
    return NewsColdStorageSummary(
        row_count=row_count,
        earliest_news_time=datetime.fromisoformat("2022-01-01T00:00:00+00:00"),
        latest_news_time=datetime.fromisoformat("2026-08-02T00:00:00+00:00"),
        rows_by_year=((2022, 1), (2026, row_count - 1)),
    )


def _consistent_verification() -> NewsColdStorageVerification:
    summary = _summary()
    return NewsColdStorageVerification(
        source=summary,
        stage=summary,
        source_missing_from_stage=0,
        stage_missing_from_source=0,
    )


def test_copy_preview_does_not_execute_write_sql(mocker) -> None:
    service = NewsColdStorageMigrationService()
    session = mocker.Mock()
    mocker.patch.object(service, "prepare")
    mocker.patch.object(service, "_load_summary", side_effect=[_summary(), _summary(row_count=1)])

    result = service.copy(session, apply=False)

    assert result.applied is False
    assert result.copy_started_at is None
    session.execute.assert_not_called()
    session.commit.assert_not_called()


def test_copy_apply_uses_partition_compatible_conflict_key(mocker) -> None:
    service = NewsColdStorageMigrationService()
    session = mocker.Mock()
    mocker.patch.object(service, "prepare")
    mocker.patch.object(service, "_load_summary", side_effect=[_summary(), _summary(row_count=1)])
    clock_result = mocker.Mock()
    clock_result.scalar_one.return_value = datetime.fromisoformat("2026-08-02T19:00:00+08:00")
    session.execute.side_effect = [clock_result, SimpleNamespace(rowcount=3)]

    result = service.copy(session, apply=True)

    copy_sql = str(session.execute.call_args_list[1].args[0])
    assert result.applied is True
    assert result.rows_affected == 3
    assert "ON CONFLICT (news_time, row_key_hash)" in copy_sql
    assert "news_time = EXCLUDED.news_time" not in copy_sql
    assert "row_key_hash = EXCLUDED.row_key_hash" not in copy_sql
    session.commit.assert_called_once()


def test_copy_apply_rolls_back_the_cli_session_when_write_fails(mocker) -> None:
    service = NewsColdStorageMigrationService()
    session = mocker.Mock()
    mocker.patch.object(service, "prepare")
    mocker.patch.object(service, "_load_summary", side_effect=[_summary(), _summary(row_count=1)])
    clock_result = mocker.Mock()
    clock_result.scalar_one.return_value = datetime.fromisoformat("2026-08-02T19:00:00+08:00")
    session.execute.side_effect = [clock_result, RuntimeError("copy failed")]

    with pytest.raises(RuntimeError, match="copy failed"):
        service.copy(session, apply=True)

    session.commit.assert_not_called()
    session.rollback.assert_called_once()


def test_cutover_preview_never_locks_or_mutates(mocker) -> None:
    service = NewsColdStorageMigrationService()
    session = mocker.Mock()
    verification = _consistent_verification()
    mocker.patch.object(service, "prepare")
    mocker.patch.object(service, "_verify_data", return_value=verification)

    result = service.cutover(session, apply=False, copy_started_at=None, drop_retired_table=False)

    assert result is verification
    session.execute.assert_not_called()
    session.rollback.assert_not_called()


def test_cutover_apply_locks_verifies_switches_and_drops_only_after_consistency(mocker) -> None:
    service = NewsColdStorageMigrationService()
    session = mocker.Mock()
    session.begin.return_value = nullcontext()
    session.execute.return_value = SimpleNamespace(rowcount=4)
    verification = _consistent_verification()
    mocker.patch.object(service, "prepare")
    mocker.patch.object(service, "_reject_existing_retired_relation")
    mocker.patch.object(service, "_verify_data", return_value=verification)

    result = service.cutover(
        session,
        apply=True,
        copy_started_at=datetime.fromisoformat("2026-08-02T19:00:00+08:00"),
        drop_retired_table=True,
    )

    sql = [str(call.args[0]) for call in session.execute.call_args_list]
    assert result.tail_rows_affected == 4
    assert any("SET LOCAL lock_timeout = '15s'" in statement for statement in sql)
    assert any("LOCK TABLE raw_tushare.news IN ACCESS EXCLUSIVE MODE" in statement for statement in sql)
    assert any("WHERE fetched_at >= :copy_started_at" in statement for statement in sql)
    assert any("ALTER TABLE raw_tushare.news RENAME TO news_retired" in statement for statement in sql)
    assert any("ALTER TABLE raw_tushare.news_partitioned_stage RENAME TO news" in statement for statement in sql)
    assert any("CREATE OR REPLACE VIEW core_serving_light.news" in statement for statement in sql)
    assert any("DROP TABLE raw_tushare.news_retired" in statement for statement in sql)


def test_cutover_rejects_apply_without_explicit_destructive_confirmation(mocker) -> None:
    service = NewsColdStorageMigrationService()
    session = mocker.Mock()
    mocker.patch.object(service, "prepare")

    try:
        service.cutover(
            session,
            apply=True,
            copy_started_at=datetime.fromisoformat("2026-08-02T19:00:00+08:00"),
            drop_retired_table=False,
        )
    except ValueError as error:
        assert "--drop-retired-table" in str(error)
    else:
        raise AssertionError("cutover apply should require explicit old-table deletion confirmation")

    session.execute.assert_not_called()
