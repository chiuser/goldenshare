"""No old date is guessed and no retained input is silently invalidated."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text, insert

from tests.wealth_watchlist_postgres_support import isolated_postgres
from tests.test_wealth_trading_assistant_persistence import seed_account
from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate


@pytest.mark.parametrize("old_kind", ["holding", "retained_input", "empty"])
def test_opened_on_migration_preserves_old_facts(tmp_path, old_kind):
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = scripts.get_revision("20260912_000172").module
    assert migration.down_revision == "20260912_000171"
    with isolated_postgres(tmp_path) as engine:
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA app"))
            conn.execute(text("CREATE TABLE app.app_user (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO app.app_user VALUES (1)"))
            with Operations.context(MigrationContext.configure(conn)):
                scripts.get_revision("20260912_000171").module.upgrade()
            account, initial, _ = seed_account(conn)
            if old_kind == "holding":
                conn.execute(text("INSERT INTO app.wealth_ta_initial_position "
                    "(initialization_id,account_id,ts_code,client_row_id,quantity,available_quantity,cost_price) "
                    "VALUES (:initial,:account,'000001.SZ','old-row',600,600,10.00)"),
                    {"initial":initial,"account":account})
            if old_kind == "retained_input":
                conn.execute(insert(ValidationCandidate).values(candidate_id=uuid4(), owner_id=1,
                    account_id=account, purpose="PREVIEW", request_id=None, input_schema_version=1,
                    input_digest=b"a"*32, input_payload={"initialPositions":[{"tsCode":"000001.SZ"}]},
                    basis={}, created_at=datetime.now(timezone.utc)))
        if old_kind != "empty":
            with pytest.raises(RuntimeError, match="must be retained"):
                with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
                    migration.upgrade()
            with engine.connect() as conn:
                assert conn.scalar(text("SELECT count(*) FROM information_schema.columns WHERE "
                    "table_schema='app' AND table_name='wealth_ta_initial_position' AND column_name='opened_on'")) == 0
                table = "wealth_ta_initial_position" if old_kind=="holding" else "wealth_ta_validation_candidate"
                assert conn.scalar(text(f"SELECT count(*) FROM app.{table}")) == 1
        else:
            with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
            with engine.connect() as conn:
                assert conn.scalar(text("SELECT is_nullable FROM information_schema.columns WHERE "
                    "table_schema='app' AND table_name='wealth_ta_initial_position' AND column_name='opened_on'")) == "NO"
