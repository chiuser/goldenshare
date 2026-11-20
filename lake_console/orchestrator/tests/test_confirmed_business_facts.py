"""Validate the registry and its command against a disposable PostgreSQL cluster."""

import json
import os
import secrets
import subprocess
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import psycopg2
import pytest
from psycopg2.extensions import make_dsn

from orchestrator.defs.confirmed_business_facts import (
    READ_URL,
    SHANGHAI,
    WRITE_URL,
    ConfirmedFactsError,
    Evidence,
    FactDetails,
    FactType,
    connect_confirmed_facts,
    correct_fact,
    find_effective_facts,
    list_fact_history,
    register_fact,
    resolve_fund_status,
    revoke_fact,
)
from orchestrator.defs.confirmed_business_facts_cli import main
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.resources import DuckDBResource
from tests.etf_daily_test_support import basic_row, make_roots, write_basic_reference

DAY_16 = date(2026, 11, 16)
DAY_17 = date(2026, 11, 17)
DAY_18 = date(2026, 11, 18)
ETF = "530080.SH"
LIQUIDATION = FactType.FUND_LIQUIDATION_STARTED
EVIDENCE = Evidence(
    "天弘基金", "https://example.test/fund-announcement", "test-article"
)


@pytest.fixture(scope="module")
def registry_urls():
    if os.environ.get("DG_CONFIRMED_FACTS_TEST_POSTGRES") != "1":
        pytest.skip(
            "Set DG_CONFIRMED_FACTS_TEST_POSTGRES=1 for the isolated PostgreSQL test"
        )
    pg_bin = Path("/opt/homebrew/opt/postgresql@18/bin")
    with TemporaryDirectory(prefix="dg-facts-", dir="/private/tmp") as directory:
        root = Path(directory)
        socket = root / "socket"
        socket.mkdir(mode=0o700)
        data = root / "data"
        password_file = root / "pw"
        password_file.write_text(secrets.token_urlsafe(24), encoding="utf-8")
        password_file.chmod(0o600)
        owner_password = password_file.read_text(encoding="utf-8")
        subprocess.run(
            [
                pg_bin / "initdb",
                "-D",
                data,
                "-U",
                "facts_test_owner",
                "--auth=scram-sha-256",
                f"--pwfile={password_file}",
                "--encoding=UTF8",
                "--no-locale",
            ],
            check=True,
            capture_output=True,
        )
        try:
            subprocess.run(
                [
                    pg_bin / "pg_ctl",
                    "-D",
                    data,
                    "-l",
                    root / "server.log",
                    "-o",
                    (
                        f"-c listen_addresses='' -c unix_socket_directories='{socket}' "
                        "-c unix_socket_permissions=0700 -p 55439"
                    ),
                    "-w",
                    "start",
                ],
                check=True,
                capture_output=True,
            )

            def dsn(user, password, database="goldenshare_lake_meta"):
                return make_dsn(
                    host=str(socket),
                    port=55439,
                    dbname=database,
                    user=user,
                    password=password,
                )

            bootstrap = psycopg2.connect(
                dsn("facts_test_owner", owner_password, "postgres")
            )
            try:
                bootstrap.autocommit = True
                with bootstrap.cursor() as cursor:
                    cursor.execute(
                        "SELECT current_setting('data_directory'), inet_server_addr()"
                    )
                    assert cursor.fetchone() == (str(data), None)
                    cursor.execute("CREATE DATABASE goldenshare_lake_meta")
            finally:
                bootstrap.close()

            read_password = secrets.token_urlsafe(24)
            write_password = secrets.token_urlsafe(24)
            owner = psycopg2.connect(dsn("facts_test_owner", owner_password))
            try:
                with owner, owner.cursor() as cursor:
                    cursor.execute(
                        "CREATE ROLE facts_test_reader LOGIN PASSWORD %s",
                        (read_password,),
                    )
                    cursor.execute(
                        "CREATE ROLE facts_test_writer LOGIN PASSWORD %s",
                        (write_password,),
                    )
                    ddl = (
                        Path(__file__).resolve().parents[1]
                        / "sql/create_confirmed_business_facts.sql"
                    )
                    cursor.execute(ddl.read_text(encoding="utf-8"))
                    cursor.execute(
                        """
                        GRANT SELECT ON public.confirmed_business_facts
                            TO facts_test_reader, facts_test_writer;
                        GRANT INSERT (fact_id, revision, action, subject_type, subject_key,
                            fact_type, time_precision, effective_from, effective_until, evidence, reason)
                            ON public.confirmed_business_facts TO facts_test_writer;
                        """
                    )
            finally:
                owner.close()
            yield (
                dsn("facts_test_reader", read_password),
                dsn("facts_test_writer", write_password),
            )
        finally:
            if (data / "postmaster.pid").exists():
                subprocess.run(
                    [pg_bin / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop"],
                    check=True,
                    capture_output=True,
                )


@pytest.fixture
def registry(monkeypatch, registry_urls):
    monkeypatch.setenv(READ_URL, registry_urls[0])
    monkeypatch.setenv(WRITE_URL, registry_urls[1])


def _read_day(day, key=ETF):
    with connect_confirmed_facts() as db:
        return find_effective_facts(
            db,
            subject_type="etf",
            fact_types=(LIQUIDATION,),
            window_start=day,
            window_end_exclusive=date.fromordinal(day.toordinal() + 1),
            subject_keys=(key,),
        )


def test_registry_history_and_fresh_retry(registry):
    initial = FactDetails(DAY_16, None, (EVIDENCE,), "公告确认 16 日起进入清算")
    with connect_confirmed_facts(writable=True) as db:
        fact = register_fact(
            db, subject_key=ETF, fact_type=LIQUIDATION, details=initial
        )
    assert fact.revision == 1 and fact.recorded_by == "facts_test_writer"
    assert not _read_day(date(2026, 11, 15))
    assert _read_day(DAY_16)[0].fact_id == fact.fact_id
    with connect_confirmed_facts(writable=True) as db:
        repeated = register_fact(
            db, subject_key=ETF, fact_type=LIQUIDATION, details=initial
        )
    assert repeated == fact

    new_details = FactDetails(DAY_18, date(2026, 11, 20), (EVIDENCE,), "公告日期更正")
    with connect_confirmed_facts(writable=True) as db:
        corrected = correct_fact(
            db, fact_id=fact.fact_id, expected_revision=1, details=new_details
        )
    assert corrected.revision == 2 and not _read_day(DAY_17)
    assert _read_day(DAY_18)[0].revision == 2
    assert not _read_day(date(2026, 11, 20))
    with connect_confirmed_facts(writable=True) as db:
        assert (
            correct_fact(
                db, fact_id=fact.fact_id, expected_revision=1, details=new_details
            ).revision
            == 2
        )
        with pytest.raises(ConfirmedFactsError, match="版本"):
            correct_fact(db, fact_id=fact.fact_id, expected_revision=1, details=initial)
    for _ in range(2):
        with connect_confirmed_facts(writable=True) as db:
            assert (
                revoke_fact(
                    db, fact_id=fact.fact_id, expected_revision=2, reason="撤销"
                ).revision
                == 3
            )
    assert not _read_day(DAY_18)
    with connect_confirmed_facts() as db:
        history = list_fact_history(db, fact_id=fact.fact_id)
        assert [(item.revision, item.action) for item in history] == [
            (3, "revoke"),
            (2, "correct"),
            (1, "confirm"),
        ]


def test_transaction_and_roles(registry, registry_urls):
    key = "159918.SZ"
    details = FactDetails(DAY_16, None, (EVIDENCE,), "隔离样本")
    with (
        pytest.raises(RuntimeError, match="interrupted"),
        connect_confirmed_facts(writable=True) as db,
    ):
        register_fact(db, subject_key=key, fact_type=LIQUIDATION, details=details)
        raise RuntimeError("interrupted before commit")
    assert not _read_day(DAY_16, key)
    with connect_confirmed_facts(writable=True) as db:
        fact = register_fact(
            db, subject_key=key, fact_type=LIQUIDATION, details=details
        )
    assert _read_day(DAY_16, key)[0].fact_id == fact.fact_id
    for url in registry_urls:
        db = psycopg2.connect(url)
        try:
            with (
                pytest.raises(psycopg2.errors.InsufficientPrivilege),
                db,
                db.cursor() as cursor,
            ):
                cursor.execute(
                    "UPDATE public.confirmed_business_facts SET reason = 'overwrite'"
                )
        finally:
            db.close()
    with (
        pytest.raises(psycopg2.errors.ReadOnlySqlTransaction),
        connect_confirmed_facts() as db,
    ):
        register_fact(
            db, subject_key="159919.SZ", fact_type=LIQUIDATION, details=details
        )


def test_cli_reads_verified_basic_and_fact(registry, tmp_path, monkeypatch, capsys):
    @contextmanager
    def isolated_duckdb(self):
        with connect_configured_duckdb(
            DuckDBConnectionSettings(temp_directory=tmp_path / "duckdb")
        ) as db:
            yield db

    monkeypatch.setattr(DuckDBResource, "connect", isolated_duckdb)
    lake_root, staging_root = make_roots(tmp_path)
    reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=[basic_row("510330.SH", list_status="L")],
    )
    reference_path = tmp_path / "reference.json"
    reference_path.write_text(reference.model_dump_json(), encoding="utf-8")
    key = "510330.SH"
    assert (
        main(
            [
                "register",
                "--subject-key",
                key,
                "--fact-type",
                str(LIQUIDATION),
                "--effective-from",
                "2026-11-16",
                "--reason",
                "隔离样本",
                "--evidence",
                "天弘基金",
                "https://example.test/test-article",
            ]
        )
        == 0
    )
    registered = json.loads(capsys.readouterr().out)
    assert registered["effective_from"] == "2026-11-16T00:00:00+08:00"
    assert (
        main(
            [
                "fund-status",
                "--subject-key",
                key,
                "--date",
                "2026-11-17",
                "--basic-reference",
                str(reference_path),
            ],
            lake_root=lake_root,
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["source_status"] == "L" and result["status"] == "清算中"
    assert result["fact"]["fact_id"] == registered["fact_id"]
    assert result["basic_reference_fingerprint"] == reference.reference_fingerprint


def test_input_validation():
    with pytest.raises(ConfirmedFactsError, match="日期"):
        FactDetails(DAY_18, DAY_17, (EVIDENCE,), "日期倒置")
    with pytest.raises(ConfirmedFactsError, match="公告"):
        FactDetails(DAY_16, None, (), "没有证据")
    with pytest.raises(ConfirmedFactsError, match="公告"):
        Evidence("", "file:///private/tmp/test")


def test_today_cannot_use_an_old_basic_reference(tmp_path, capsys):
    with pytest.raises(SystemExit) as problem:
        main(
            [
                "fund-status",
                "--subject-key",
                ETF,
                "--date",
                datetime.now(SHANGHAI).date().isoformat(),
                "--basic-reference",
                str(tmp_path / "old-snapshot.json"),
            ],
            lake_root=tmp_path,
        )
    assert problem.value.code == 1
    assert "最新已核验" in capsys.readouterr().err


def test_registered_delisting_takes_precedence_on_its_effective_date(registry):
    key = "159920.SZ"
    with connect_confirmed_facts(writable=True) as db:
        register_fact(
            db,
            subject_key=key,
            fact_type=LIQUIDATION,
            details=FactDetails(DAY_16, None, (EVIDENCE,), "清算公告"),
        )
        delisted = register_fact(
            db,
            subject_key=key,
            fact_type=FactType.FUND_DELISTED,
            details=FactDetails(DAY_18, None, (EVIDENCE,), "终止上市公告"),
        )
    with connect_confirmed_facts() as db:
        previous_day = find_effective_facts(
            db,
            subject_type="etf",
            fact_types=tuple(FactType),
            window_start=DAY_17,
            window_end_exclusive=DAY_18,
            subject_keys=(key,),
        )
        next_day = find_effective_facts(
            db,
            subject_type="etf",
            fact_types=tuple(FactType),
            window_start=DAY_18,
            window_end_exclusive=date(2026, 11, 19),
            subject_keys=(key,),
        )
    assert (
        resolve_fund_status(
            subject_key=key,
            business_date=DAY_17,
            source_status="L",
            effective_facts=previous_day,
        ).status
        == "清算中"
    )
    result = resolve_fund_status(
        subject_key=key,
        business_date=DAY_18,
        source_status="L",
        effective_facts=next_day,
    )
    assert result.status == "退市" and result.fact == delisted
