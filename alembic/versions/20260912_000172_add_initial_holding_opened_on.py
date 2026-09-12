"""Require user-supplied initial holding dates; never invent historical facts."""
from alembic import op
import sqlalchemy as sa

revision = "20260912_000172"
down_revision = "20260912_000171"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # Old rows have no source for an actual opening date. Stop before DDL and
    # require an explicitly reviewed data migration rather than silently fill it.
    if connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM app.wealth_ta_initial_position)")):
        raise RuntimeError("Existing initial holdings need user-supplied dates; data must be retained")
    for table in ("wealth_ta_write_request", "wealth_ta_validation_candidate"):
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM app.{table} WHERE "
                "jsonb_path_exists(input_payload, '$.initialPositions[*] ? (!exists(@.openedOn))'))")):
            raise RuntimeError("Retained initial holding inputs need user-supplied dates; data must be retained")
    op.add_column("wealth_ta_initial_position", sa.Column("opened_on", sa.Date(), nullable=False), schema="app")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM app.wealth_ta_initial_position)")):
        raise RuntimeError("Initial holding dates must be retained; refusing destructive downgrade")
    op.drop_column("wealth_ta_initial_position", "opened_on", schema="app")
