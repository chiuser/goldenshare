"""Allow a failed calculation to remain retained without automatic scheduling."""
from alembic import op
import sqlalchemy as sa

revision = "20260912_000175"
down_revision = "20260912_000174"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("wealth_ta_recalculation", "next_attempt_at", schema="app",
                    existing_type=sa.DateTime(timezone=True), nullable=True)


def downgrade():
    # Never invent a retry time or remove retained work to satisfy an old schema.
    op.alter_column("wealth_ta_recalculation", "next_attempt_at", schema="app",
                    existing_type=sa.DateTime(timezone=True), nullable=False)
