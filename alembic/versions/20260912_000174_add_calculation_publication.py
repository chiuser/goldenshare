"""Frozen M3 daily snapshot and publication DDL; no production execution."""
from alembic import op
import sqlalchemy as sa

revision = "20260912_000174"
down_revision = "20260912_000173"
branch_labels = None
depends_on = None

STATEMENTS = (
    r"""
CREATE TABLE app.wealth_ta_account_snapshot (
	account_id UUID NOT NULL,
	day_result_id UUID NOT NULL,
	trade_date DATE NOT NULL,
	valuation_at TIMESTAMP WITH TIME ZONE NOT NULL,
	cash_amount NUMERIC,
	stock_market_value NUMERIC NOT NULL,
	total_assets NUMERIC,
	cash_in_amount NUMERIC NOT NULL,
	cash_out_amount NUMERIC NOT NULL,
	current_buy_input NUMERIC NOT NULL,
	current_sell_net NUMERIC NOT NULL,
	dynamic_cost_amount NUMERIC NOT NULL,
	estimated_sell_commission NUMERIC NOT NULL,
	estimated_stamp_tax NUMERIC NOT NULL,
	estimated_net_proceeds NUMERIC NOT NULL,
	holding_profit_amount NUMERIC NOT NULL,
	holding_return_pct NUMERIC,
	day_profit_amount NUMERIC,
	day_capital_amount NUMERIC,
	day_return_pct NUMERIC,
	closed_trade_count BIGINT NOT NULL,
	closed_profit_amount NUMERIC NOT NULL,
	CONSTRAINT pk_wealth_ta_account_snapshot PRIMARY KEY (account_id, day_result_id),
	CONSTRAINT fk_wealth_ta_account_snapshot_account_id_wealth_ta_day_result FOREIGN KEY(account_id, trade_date, day_result_id) REFERENCES app.wealth_ta_day_result (account_id, trade_date, day_result_id) ON DELETE RESTRICT,
	CONSTRAINT ck_wealth_ta_account_snapshot_cash_history CHECK ((cash_amount IS NULL AND total_assets IS NULL) OR (cash_amount IS NOT NULL AND total_assets IS NOT NULL AND cash_amount >= 0 AND total_assets = cash_amount + stock_market_value)),
	CONSTRAINT ck_wealth_ta_account_snapshot_nonnegative CHECK (closed_trade_count >= 0 AND current_buy_input >= 0 AND stock_market_value >= 0 AND cash_in_amount >= 0 AND cash_out_amount >= 0 AND estimated_sell_commission >= 0 AND estimated_stamp_tax >= 0),
	CONSTRAINT ck_wealth_ta_account_snapshot_valuation CHECK (dynamic_cost_amount = current_buy_input - current_sell_net AND estimated_net_proceeds = stock_market_value - estimated_sell_commission - estimated_stamp_tax AND holding_profit_amount = current_sell_net + estimated_net_proceeds - current_buy_input),
	CONSTRAINT ck_wealth_ta_account_snapshot_holding_return CHECK ((current_buy_input > 0 AND holding_return_pct IS NOT NULL) OR (current_buy_input = 0 AND holding_return_pct IS NULL AND holding_profit_amount = 0)),
	CONSTRAINT ck_wealth_ta_account_snapshot_day_return CHECK ((day_profit_amount IS NULL AND day_capital_amount IS NULL AND day_return_pct IS NULL) OR (day_profit_amount IS NOT NULL AND day_capital_amount IS NOT NULL AND day_capital_amount > 0 AND day_return_pct IS NOT NULL)),
	CONSTRAINT ck_wealth_ta_account_snapshot_cash_amount CHECK (cash_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND cash_amount = trunc(cash_amount, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_stock_market_value CHECK (stock_market_value NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND stock_market_value = trunc(stock_market_value, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_total_assets CHECK (total_assets NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND total_assets = trunc(total_assets, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_cash_in_amount CHECK (cash_in_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND cash_in_amount = trunc(cash_in_amount, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_cash_out_amount CHECK (cash_out_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND cash_out_amount = trunc(cash_out_amount, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_current_buy_input CHECK (current_buy_input NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND current_buy_input = trunc(current_buy_input, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_current_sell_net CHECK (current_sell_net NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND current_sell_net = trunc(current_sell_net, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_dynamic_cost_amount CHECK (dynamic_cost_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND dynamic_cost_amount = trunc(dynamic_cost_amount, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_estimated_sell_commission CHECK (estimated_sell_commission NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND estimated_sell_commission = trunc(estimated_sell_commission, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_estimated_stamp_tax CHECK (estimated_stamp_tax NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND estimated_stamp_tax = trunc(estimated_stamp_tax, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_estimated_net_proceeds CHECK (estimated_net_proceeds NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND estimated_net_proceeds = trunc(estimated_net_proceeds, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_holding_profit_amount CHECK (holding_profit_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND holding_profit_amount = trunc(holding_profit_amount, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_holding_return_pct CHECK (holding_return_pct NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND holding_return_pct = trunc(holding_return_pct, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_day_profit_amount CHECK (day_profit_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND day_profit_amount = trunc(day_profit_amount, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_day_capital_amount CHECK (day_capital_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND day_capital_amount = trunc(day_capital_amount, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_day_return_pct CHECK (day_return_pct NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND day_return_pct = trunc(day_return_pct, 2)),
	CONSTRAINT ck_wealth_ta_account_snapshot_closed_profit_amount CHECK (closed_profit_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND closed_profit_amount = trunc(closed_profit_amount, 2))
)
""",
    r"""
CREATE TABLE app.wealth_ta_publication_day (
	account_id UUID NOT NULL,
	generation_id UUID NOT NULL,
	trade_date DATE NOT NULL,
	day_result_id UUID NOT NULL,
	CONSTRAINT pk_wealth_ta_publication_day PRIMARY KEY (account_id, generation_id, trade_date),
	CONSTRAINT fk_wealth_ta_publication_day_account_id_wealth_ta_calcu_49fe FOREIGN KEY(account_id, generation_id) REFERENCES app.wealth_ta_calculation_generation (account_id, generation_id) ON DELETE RESTRICT,
	CONSTRAINT fk_wealth_ta_publication_day_account_id_wealth_ta_day_result FOREIGN KEY(account_id, trade_date, day_result_id) REFERENCES app.wealth_ta_day_result (account_id, trade_date, day_result_id) ON DELETE RESTRICT
)
""",
    r"""
CREATE TABLE app.wealth_ta_publication_receipt (
	account_id UUID NOT NULL,
	generation_id UUID NOT NULL,
	target_version BIGINT NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE NOT NULL,
	manifest_digest BYTEA NOT NULL,
	day_count BIGINT NOT NULL,
	CONSTRAINT pk_wealth_ta_publication_receipt PRIMARY KEY (account_id, generation_id),
	CONSTRAINT fk_wealth_ta_publication_receipt_account_id_wealth_ta_c_5feb FOREIGN KEY(account_id, generation_id) REFERENCES app.wealth_ta_calculation_generation (account_id, generation_id) ON DELETE RESTRICT,
	CONSTRAINT ck_wealth_ta_publication_receipt_receipt CHECK (target_version >= 1 AND day_count >= 0 AND octet_length(manifest_digest) = 32)
)
""",
)


def upgrade():
    for statement in STATEMENTS:
        op.execute(sa.text(statement))


def downgrade():
    connection = op.get_bind()
    tables = ("wealth_ta_publication_receipt", "wealth_ta_publication_day", "wealth_ta_account_snapshot")
    for table in tables:
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM app.{table})")):
            raise RuntimeError("Published accounting results must be retained; refusing destructive downgrade")
    for table in tables:
        op.drop_table(table, schema="app")
