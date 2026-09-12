"""Frozen M3 input and batch DDL; no production execution."""
from alembic import op
import sqlalchemy as sa

revision = "20260912_000173"
down_revision = "20260912_000172"
branch_labels = None
depends_on = None

STATEMENTS = (
    r"""
CREATE TABLE app.wealth_ta_valuation_basis (
	basis_id UUID NOT NULL,
	account_id UUID NOT NULL,
	generation_id UUID NOT NULL,
	ts_code TEXT NOT NULL,
	trade_date DATE NOT NULL,
	valuation_at TIMESTAMP WITH TIME ZONE NOT NULL,
	price NUMERIC,
	source_ref TEXT NOT NULL,
	source_version TEXT NOT NULL,
	quality TEXT NOT NULL,
	fee_version_id UUID NOT NULL,
	valuation_method TEXT,
	price_date DATE,
	suspension_evidence_ref TEXT,
	CONSTRAINT pk_wealth_ta_valuation_basis PRIMARY KEY (basis_id),
	CONSTRAINT uq_ta_valuation_stock_day UNIQUE (account_id, generation_id, trade_date, ts_code),
	CONSTRAINT fk_wealth_ta_valuation_basis_account_id_wealth_ta_calcu_d617 FOREIGN KEY(account_id, generation_id) REFERENCES app.wealth_ta_calculation_generation (account_id, generation_id) ON DELETE RESTRICT,
	CONSTRAINT fk_wealth_ta_valuation_basis_account_id_wealth_ta_fee_version FOREIGN KEY(account_id, fee_version_id) REFERENCES app.wealth_ta_fee_version (account_id, fee_version_id) ON DELETE RESTRICT,
	CONSTRAINT ck_wealth_ta_valuation_basis_price CHECK (price IS NULL OR (price > 0 AND price NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric))),
	CONSTRAINT ck_wealth_ta_valuation_basis_availability CHECK ((quality = 'READY' AND price IS NOT NULL AND price_date IS NOT NULL AND valuation_method IS NOT NULL AND ((valuation_method = 'SAME_DAY_CLOSE' AND price_date = trade_date AND suspension_evidence_ref IS NULL) OR (valuation_method = 'CONFIRMED_SUSPENSION_CARRY' AND price_date < trade_date AND suspension_evidence_ref IS NOT NULL))) OR (quality = 'UNAVAILABLE' AND price IS NULL AND price_date IS NULL AND valuation_method IS NULL AND suspension_evidence_ref IS NULL))
)

""",
    r"""
CREATE TABLE app.wealth_ta_calculation_batch (
	account_id UUID NOT NULL,
	generation_id UUID NOT NULL,
	trade_date DATE NOT NULL,
	stage TEXT NOT NULL,
	stock_key TEXT NOT NULL,
	page_key TEXT NOT NULL,
	cursor JSONB NOT NULL,
	accumulator JSONB NOT NULL,
	input_digest BYTEA NOT NULL,
	row_count BIGINT NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_wealth_ta_calculation_batch PRIMARY KEY (account_id, generation_id, trade_date, stage, stock_key, page_key),
	CONSTRAINT fk_wealth_ta_calculation_batch_account_id_wealth_ta_cal_a004 FOREIGN KEY(account_id, generation_id) REFERENCES app.wealth_ta_calculation_generation (account_id, generation_id) ON DELETE RESTRICT,
	CONSTRAINT ck_wealth_ta_calculation_batch_batch_values CHECK (row_count >= 0 AND octet_length(input_digest) = 32),
	CONSTRAINT ck_wealth_ta_calculation_batch_batch_identity CHECK (length(stage) > 0 AND length(page_key) > 0)
)

""",
)


def upgrade():
    for statement in STATEMENTS:
        op.execute(sa.text(statement))


def downgrade():
    connection = op.get_bind()
    for table in ("wealth_ta_calculation_batch", "wealth_ta_valuation_basis"):
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM app.{table})")):
            raise RuntimeError("Calculation inputs must be retained; refusing destructive downgrade")
    op.drop_table("wealth_ta_calculation_batch", schema="app")
    op.drop_table("wealth_ta_valuation_basis", schema="app")
