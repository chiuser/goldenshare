"""M2 accounting facts, write recovery and dependent result storage.

Frozen PostgreSQL DDL; no mutable application model imports.
Does not activate calculation, routes or a production migration.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260912_000171"
down_revision = "20260907_000170"
branch_labels = None
depends_on = None


STATEMENTS = (
    r"""
CREATE TABLE app.wealth_ta_account (
	account_id UUID NOT NULL,
	owner_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	broker_name TEXT NOT NULL,
	initialized_on DATE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	current_initialization_id UUID NOT NULL,
	current_fee_version_id UUID NOT NULL,
	fact_version BIGINT NOT NULL,
	calculation_target_version BIGINT NOT NULL,
	published_generation_id UUID,
	CONSTRAINT pk_wealth_ta_account PRIMARY KEY (account_id),
	CONSTRAINT uq_wealth_ta_account_owner_id UNIQUE (owner_id, account_id),
	CONSTRAINT ck_wealth_ta_account_names CHECK (length(btrim(name)) > 0 AND length(btrim(broker_name)) > 0),
	CONSTRAINT ck_wealth_ta_account_versions CHECK (fact_version >= 1 AND calculation_target_version >= 1),
	CONSTRAINT fk_wealth_ta_account_owner_id_app_user FOREIGN KEY(owner_id) REFERENCES app.app_user (id) ON DELETE RESTRICT
)
    """,
    r"""
CREATE INDEX idx_ta_account_owner_order ON app.wealth_ta_account (owner_id, created_at, account_id)
    """,
    r"""
CREATE TABLE app.wealth_ta_write_scope (
	owner_id INTEGER NOT NULL,
	scope_key TEXT NOT NULL,
	holder_request_id UUID,
	CONSTRAINT pk_wealth_ta_write_scope PRIMARY KEY (owner_id, scope_key),
	CONSTRAINT ck_wealth_ta_write_scope_scope_key CHECK (length(scope_key) > 0),
	CONSTRAINT fk_wealth_ta_write_scope_owner_id_app_user FOREIGN KEY(owner_id) REFERENCES app.app_user (id) ON DELETE RESTRICT
)
    """,
    r"""
CREATE TABLE app.wealth_ta_fee_version (
	fee_version_id UUID NOT NULL,
	account_id UUID NOT NULL,
	commission_rate NUMERIC NOT NULL,
	minimum_commission NUMERIC NOT NULL,
	stamp_tax_rate NUMERIC NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_wealth_ta_fee_version PRIMARY KEY (fee_version_id),
	CONSTRAINT uq_wealth_ta_fee_version_account_id UNIQUE (account_id, fee_version_id),
	CONSTRAINT ck_wealth_ta_fee_version_commission CHECK (commission_rate NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND commission_rate = trunc(commission_rate, 6) AND commission_rate >= 0),
	CONSTRAINT ck_wealth_ta_fee_version_minimum CHECK (minimum_commission NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND minimum_commission = trunc(minimum_commission, 2) AND minimum_commission >= 0),
	CONSTRAINT ck_wealth_ta_fee_version_tax CHECK (stamp_tax_rate NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND stamp_tax_rate = trunc(stamp_tax_rate, 4) AND stamp_tax_rate >= 0 AND stamp_tax_rate <= 1),
	CONSTRAINT fk_wealth_ta_fee_version_account_id_wealth_ta_account FOREIGN KEY(account_id) REFERENCES app.wealth_ta_account (account_id) ON DELETE RESTRICT
)
    """,
    r"""
CREATE TABLE app.wealth_ta_initialization (
	initialization_id UUID NOT NULL,
	account_id UUID NOT NULL,
	revision BIGINT NOT NULL,
	accepted_fact_version BIGINT NOT NULL,
	initial_cash NUMERIC NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	source_initialization_id UUID,
	CONSTRAINT pk_wealth_ta_initialization PRIMARY KEY (initialization_id),
	CONSTRAINT uq_ta_initialization_identity UNIQUE (account_id, initialization_id),
	CONSTRAINT uq_ta_initialization_revision UNIQUE (account_id, revision),
	CONSTRAINT ck_wealth_ta_initialization_versions CHECK (revision >= 1 AND accepted_fact_version >= 1),
	CONSTRAINT ck_wealth_ta_initialization_source CHECK ((revision = 1 AND source_initialization_id IS NULL) OR (revision > 1 AND source_initialization_id IS NOT NULL AND source_initialization_id <> initialization_id)),
	CONSTRAINT ck_wealth_ta_initialization_cash CHECK (initial_cash NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND initial_cash = trunc(initial_cash, 2) AND initial_cash >= 0),
	CONSTRAINT fk_wealth_ta_initialization_account_id_wealth_ta_initialization FOREIGN KEY(account_id, source_initialization_id) REFERENCES app.wealth_ta_initialization (account_id, initialization_id) ON DELETE RESTRICT,
	CONSTRAINT fk_wealth_ta_initialization_account_id_wealth_ta_account FOREIGN KEY(account_id) REFERENCES app.wealth_ta_account (account_id) ON DELETE RESTRICT
)
    """,
    r"""
CREATE TABLE app.wealth_ta_ledger (
	ledger_id UUID NOT NULL,
	account_id UUID NOT NULL,
	kind TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_wealth_ta_ledger PRIMARY KEY (ledger_id),
	CONSTRAINT uq_wealth_ta_ledger_account_id UNIQUE (account_id, ledger_id, kind),
	CONSTRAINT ck_wealth_ta_ledger_kind CHECK (kind IN ('TRADE', 'CASH_FLOW')),
	CONSTRAINT fk_wealth_ta_ledger_account_id_wealth_ta_account FOREIGN KEY(account_id) REFERENCES app.wealth_ta_account (account_id) ON DELETE RESTRICT
)
    """,
    r"""
CREATE TABLE app.wealth_ta_write_request (
	owner_id INTEGER NOT NULL,
	request_id UUID NOT NULL,
	scope_key TEXT NOT NULL,
	operation_type TEXT NOT NULL,
	input_schema_version INTEGER NOT NULL,
	target JSONB,
	input_digest BYTEA NOT NULL,
	input_payload JSONB,
	candidate_id UUID,
	current_attempt_id UUID NOT NULL,
	state_version BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_wealth_ta_write_request PRIMARY KEY (owner_id, request_id),
	CONSTRAINT uq_ta_request_scope_identity UNIQUE (owner_id, scope_key, request_id),
	CONSTRAINT fk_wealth_ta_write_request_owner_id_wealth_ta_write_scope FOREIGN KEY(owner_id, scope_key) REFERENCES app.wealth_ta_write_scope (owner_id, scope_key) ON DELETE RESTRICT,
	CONSTRAINT ck_wealth_ta_write_request_identity CHECK (state_version >= 0 AND input_schema_version > 0 AND octet_length(input_digest) = 32),
	CONSTRAINT ck_wealth_ta_write_request_input_source CHECK ((input_payload IS NOT NULL AND candidate_id IS NULL) OR (input_payload IS NULL AND candidate_id IS NOT NULL)),
	CONSTRAINT ck_wealth_ta_write_request_target CHECK (CASE WHEN operation_type IN ('TRADE_CORRECT','TRADE_VOID','CASH_FLOW_CORRECT','CASH_FLOW_VOID') THEN COALESCE(jsonb_typeof(target) = 'object' AND target ?& ARRAY['accountId','kind','recordId'] AND target - ARRAY['accountId','kind','recordId'] = '{}'::jsonb AND scope_key = 'ACCOUNT_LEDGER:' || (target->>'accountId') AND (target->>'recordId') ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND target->>'kind' = CASE WHEN operation_type LIKE 'TRADE_%' THEN 'TRADE' ELSE 'CASH_FLOW' END, false) ELSE target IS NULL END),
	CONSTRAINT fk_wealth_ta_write_request_owner_id_app_user FOREIGN KEY(owner_id) REFERENCES app.app_user (id) ON DELETE RESTRICT
)
    """,
    r"""
CREATE TABLE app.wealth_ta_validation_candidate (
	candidate_id UUID NOT NULL,
	owner_id INTEGER NOT NULL,
	account_id UUID,
	purpose TEXT NOT NULL,
	request_id UUID,
	input_schema_version INTEGER NOT NULL,
	input_digest BYTEA NOT NULL,
	input_payload JSONB NOT NULL,
	basis JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_wealth_ta_validation_candidate PRIMARY KEY (candidate_id),
	CONSTRAINT uq_ta_candidate_request UNIQUE (owner_id, request_id),
	CONSTRAINT uq_ta_candidate_identity UNIQUE (owner_id, request_id, candidate_id),
	CONSTRAINT fk_wealth_ta_validation_candidate_owner_id_wealth_ta_account FOREIGN KEY(owner_id, account_id) REFERENCES app.wealth_ta_account (owner_id, account_id) ON DELETE RESTRICT,
	CONSTRAINT ck_wealth_ta_validation_candidate_purpose CHECK ((purpose = 'PREVIEW' AND request_id IS NULL) OR (purpose = 'SAVE' AND request_id IS NOT NULL)),
	CONSTRAINT ck_wealth_ta_validation_candidate_input CHECK (input_schema_version > 0 AND octet_length(input_digest) = 32),
	CONSTRAINT fk_wealth_ta_validation_candidate_owner_id_app_user FOREIGN KEY(owner_id) REFERENCES app.app_user (id) ON DELETE RESTRICT
)
    """,
    r"""
CREATE TABLE app.wealth_ta_recalculation (
	account_id UUID NOT NULL,
	target_version BIGINT NOT NULL,
	affected_from_date DATE NOT NULL,
	next_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL,
	last_claimed_at TIMESTAMP WITH TIME ZONE,
	executor_id TEXT,
	fence BIGINT NOT NULL,
	lease_until TIMESTAMP WITH TIME ZONE,
	transient_failure_count INTEGER NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_wealth_ta_recalculation PRIMARY KEY (account_id),
	CONSTRAINT ck_wealth_ta_recalculation_counters CHECK (target_version >= 1 AND fence >= 0 AND transient_failure_count >= 0),
	CONSTRAINT fk_wealth_ta_recalculation_account_id_wealth_ta_account FOREIGN KEY(account_id) REFERENCES app.wealth_ta_account (account_id) ON DELETE RESTRICT
)
    """,
    r"""
CREATE INDEX idx_ta_recalculation_due ON app.wealth_ta_recalculation (next_attempt_at, last_claimed_at, account_id)
    """,
    r"""
CREATE TABLE app.wealth_ta_initial_position (
	initialization_id UUID NOT NULL,
	ts_code TEXT NOT NULL,
	account_id UUID NOT NULL,
	client_row_id TEXT NOT NULL,
	quantity BIGINT NOT NULL,
	available_quantity BIGINT NOT NULL,
	cost_price NUMERIC NOT NULL,
	CONSTRAINT pk_wealth_ta_initial_position PRIMARY KEY (initialization_id, ts_code),
	CONSTRAINT fk_wealth_ta_initial_position_account_id_wealth_ta_init_d911 FOREIGN KEY(account_id, initialization_id) REFERENCES app.wealth_ta_initialization (account_id, initialization_id) ON DELETE RESTRICT,
	CONSTRAINT uq_wealth_ta_initial_position_initialization_id UNIQUE (initialization_id, client_row_id),
	CONSTRAINT ck_wealth_ta_initial_position_quantity CHECK (quantity BETWEEN 1 AND 9007199254740991 AND available_quantity BETWEEN 0 AND quantity),
	CONSTRAINT ck_wealth_ta_initial_position_identity CHECK (length(client_row_id) > 0 AND length(ts_code) > 0),
	CONSTRAINT ck_wealth_ta_initial_position_cost CHECK (cost_price NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND cost_price = trunc(cost_price, 2) AND cost_price > 0)
)
    """,
    r"""
CREATE TABLE app.wealth_ta_ledger_revision (
	ledger_id UUID NOT NULL,
	revision BIGINT NOT NULL,
	account_id UUID NOT NULL,
	kind TEXT NOT NULL,
	accepted_fact_version BIGINT NOT NULL,
	occurred_on DATE NOT NULL,
	status TEXT NOT NULL,
	accepted_at TIMESTAMP WITH TIME ZONE NOT NULL,
	source_revision BIGINT,
	note TEXT,
	direction TEXT NOT NULL,
	net_cash_change NUMERIC NOT NULL,
	ts_code TEXT,
	price NUMERIC,
	quantity BIGINT,
	gross_amount NUMERIC,
	fee_version_id UUID,
	commission_rate NUMERIC,
	minimum_commission NUMERIC,
	stamp_tax_rate NUMERIC,
	commission_amount NUMERIC,
	stamp_tax_amount NUMERIC,
	cash_amount NUMERIC,
	CONSTRAINT pk_wealth_ta_ledger_revision PRIMARY KEY (ledger_id, revision),
	CONSTRAINT fk_wealth_ta_ledger_revision_account_id_wealth_ta_ledger FOREIGN KEY(account_id, ledger_id, kind) REFERENCES app.wealth_ta_ledger (account_id, ledger_id, kind) ON DELETE RESTRICT,
	CONSTRAINT fk_wealth_ta_ledger_revision_ledger_id_wealth_ta_ledger_c508 FOREIGN KEY(ledger_id, source_revision) REFERENCES app.wealth_ta_ledger_revision (ledger_id, revision) ON DELETE RESTRICT,
	CONSTRAINT fk_wealth_ta_ledger_revision_account_id_wealth_ta_fee_version FOREIGN KEY(account_id, fee_version_id) REFERENCES app.wealth_ta_fee_version (account_id, fee_version_id) ON DELETE RESTRICT,
	CONSTRAINT uq_ta_ledger_fact_version UNIQUE (account_id, accepted_fact_version),
	CONSTRAINT uq_ta_ledger_revision_identity UNIQUE (account_id, ledger_id, revision),
	CONSTRAINT ck_wealth_ta_ledger_revision_versions CHECK (revision >= 1 AND accepted_fact_version >= 1),
	CONSTRAINT ck_wealth_ta_ledger_revision_source CHECK ((revision = 1 AND source_revision IS NULL) OR (revision > 1 AND source_revision IS NOT NULL AND source_revision = revision - 1)),
	CONSTRAINT ck_wealth_ta_ledger_revision_status CHECK (status IN ('ACTIVE', 'VOID')),
	CONSTRAINT ck_wealth_ta_ledger_revision_branch CHECK ((kind = 'TRADE' AND direction IN ('BUY', 'SELL') AND cash_amount IS NULL AND ts_code IS NOT NULL AND price IS NOT NULL AND quantity IS NOT NULL AND gross_amount IS NOT NULL AND fee_version_id IS NOT NULL AND commission_rate IS NOT NULL AND minimum_commission IS NOT NULL AND stamp_tax_rate IS NOT NULL AND commission_amount IS NOT NULL AND stamp_tax_amount IS NOT NULL) OR (kind = 'CASH_FLOW' AND direction IN ('IN', 'OUT') AND cash_amount IS NOT NULL AND ts_code IS NULL AND price IS NULL AND quantity IS NULL AND gross_amount IS NULL AND fee_version_id IS NULL AND commission_rate IS NULL AND minimum_commission IS NULL AND stamp_tax_rate IS NULL AND commission_amount IS NULL AND stamp_tax_amount IS NULL)),
	CONSTRAINT ck_wealth_ta_ledger_revision_quantity CHECK (kind <> 'TRADE' OR (quantity BETWEEN 1 AND 9007199254740991 AND length(ts_code) > 0)),
	CONSTRAINT ck_wealth_ta_ledger_revision_trade_numbers CHECK (kind <> 'TRADE' OR (price NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND price = trunc(price, 2) AND price > 0 AND gross_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND gross_amount = trunc(gross_amount, 2) AND gross_amount > 0 AND commission_rate NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND commission_rate = trunc(commission_rate, 6) AND commission_rate >= 0 AND minimum_commission NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND minimum_commission = trunc(minimum_commission, 2) AND minimum_commission >= 0 AND stamp_tax_rate NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND stamp_tax_rate = trunc(stamp_tax_rate, 4) AND stamp_tax_rate >= 0 AND stamp_tax_rate <= 1 AND commission_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND commission_amount = trunc(commission_amount, 2) AND commission_amount >= 0 AND stamp_tax_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND stamp_tax_amount = trunc(stamp_tax_amount, 2) AND stamp_tax_amount >= 0)),
	CONSTRAINT ck_wealth_ta_ledger_revision_cash_amount CHECK (kind <> 'CASH_FLOW' OR (cash_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND cash_amount = trunc(cash_amount, 2) AND cash_amount > 0)),
	CONSTRAINT ck_wealth_ta_ledger_revision_cash_conservation CHECK ((kind = 'TRADE' AND gross_amount = price * quantity AND ((direction = 'BUY' AND stamp_tax_amount = 0 AND net_cash_change = -(gross_amount + commission_amount)) OR (direction = 'SELL' AND net_cash_change = gross_amount - commission_amount - stamp_tax_amount))) OR (kind = 'CASH_FLOW' AND ((direction = 'IN' AND net_cash_change = cash_amount) OR (direction = 'OUT' AND net_cash_change = -cash_amount))))
)
    """,
    r"""
CREATE INDEX idx_ta_revision_effective ON app.wealth_ta_ledger_revision (account_id, ledger_id, accepted_fact_version)
    """,
    r"""
CREATE TABLE app.wealth_ta_write_attempt (
	owner_id INTEGER NOT NULL,
	request_id UUID NOT NULL,
	attempt_id UUID NOT NULL,
	status TEXT NOT NULL,
	fence BIGINT NOT NULL,
	executor_id TEXT,
	lease_until TIMESTAMP WITH TIME ZONE,
	basis JSONB NOT NULL,
	checkpoint_ref UUID,
	receipt JSONB,
	rejection JSONB,
	started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	finished_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_wealth_ta_write_attempt PRIMARY KEY (owner_id, request_id, attempt_id),
	CONSTRAINT fk_wealth_ta_write_attempt_owner_id_wealth_ta_write_request FOREIGN KEY(owner_id, request_id) REFERENCES app.wealth_ta_write_request (owner_id, request_id) ON DELETE RESTRICT,
	CONSTRAINT ck_wealth_ta_write_attempt_fence CHECK (fence >= 1),
	CONSTRAINT ck_wealth_ta_write_attempt_status CHECK ((status = 'PROCESSING' AND receipt IS NULL AND rejection IS NULL AND finished_at IS NULL AND executor_id IS NOT NULL AND lease_until IS NOT NULL) OR (status = 'SAVED' AND receipt IS NOT NULL AND rejection IS NULL AND finished_at IS NOT NULL) OR (status = 'NOT_SAVED' AND receipt IS NULL AND rejection IS NOT NULL AND finished_at IS NOT NULL))
)
    """,
    r"""
CREATE INDEX idx_ta_attempt_expired ON app.wealth_ta_write_attempt (lease_until, owner_id, request_id, attempt_id) WHERE status = 'PROCESSING'
    """,
    r"""
CREATE UNIQUE INDEX uq_ta_attempt_processing ON app.wealth_ta_write_attempt (owner_id, request_id) WHERE status = 'PROCESSING'
    """,
    r"""
CREATE UNIQUE INDEX uq_ta_attempt_saved ON app.wealth_ta_write_attempt (owner_id, request_id) WHERE status = 'SAVED'
    """,
    r"""
CREATE TABLE app.wealth_ta_validation_checkpoint (
	checkpoint_id UUID NOT NULL,
	candidate_id UUID NOT NULL,
	validation_run_id UUID NOT NULL,
	attempt_id UUID,
	stage TEXT NOT NULL,
	stock_key TEXT NOT NULL,
	page_key TEXT NOT NULL,
	basis_digest BYTEA NOT NULL,
	cursor JSONB NOT NULL,
	accumulator JSONB NOT NULL,
	completed_range JSONB NOT NULL,
	checked_row_count BIGINT NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_wealth_ta_validation_checkpoint PRIMARY KEY (checkpoint_id),
	CONSTRAINT uq_ta_validation_page UNIQUE (candidate_id, validation_run_id, stage, stock_key, page_key),
	CONSTRAINT ck_wealth_ta_validation_checkpoint_progress CHECK (checked_row_count >= 0 AND octet_length(basis_digest) = 32),
	CONSTRAINT fk_wealth_ta_validation_checkpoint_candidate_id_wealth__d272 FOREIGN KEY(candidate_id) REFERENCES app.wealth_ta_validation_candidate (candidate_id) ON DELETE RESTRICT
)
    """,
    r"""
CREATE TABLE app.wealth_ta_calculation_generation (
	generation_id UUID NOT NULL,
	account_id UUID NOT NULL,
	target_version BIGINT NOT NULL,
	fact_version BIGINT NOT NULL,
	initialization_id UUID NOT NULL,
	rule_version BIGINT NOT NULL,
	from_date DATE NOT NULL,
	through_date DATE NOT NULL,
	stage TEXT NOT NULL,
	resume_stage TEXT,
	completed_trade_date_count BIGINT NOT NULL,
	total_trade_date_count BIGINT,
	last_completed_trade_date DATE,
	last_business_updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	reason TEXT,
	CONSTRAINT pk_wealth_ta_calculation_generation PRIMARY KEY (generation_id),
	CONSTRAINT uq_ta_generation_target UNIQUE (account_id, target_version),
	CONSTRAINT uq_ta_generation_identity UNIQUE (account_id, generation_id),
	CONSTRAINT fk_wealth_ta_calculation_generation_account_id_wealth_t_77cc FOREIGN KEY(account_id, initialization_id) REFERENCES app.wealth_ta_initialization (account_id, initialization_id) ON DELETE RESTRICT,
	CONSTRAINT ck_wealth_ta_calculation_generation_versions CHECK (target_version >= 1 AND fact_version >= 1 AND rule_version >= 1),
	CONSTRAINT ck_wealth_ta_calculation_generation_progress CHECK (from_date <= through_date AND completed_trade_date_count >= 0 AND (total_trade_date_count IS NULL OR total_trade_date_count >= completed_trade_date_count)),
	CONSTRAINT fk_wealth_ta_calculation_generation_account_id_wealth_t_278d FOREIGN KEY(account_id) REFERENCES app.wealth_ta_account (account_id) ON DELETE RESTRICT
)
    """,
    r"""
CREATE TABLE app.wealth_ta_day_result (
	day_result_id UUID NOT NULL,
	account_id UUID NOT NULL,
	origin_generation_id UUID NOT NULL,
	trade_date DATE NOT NULL,
	input_digest BYTEA NOT NULL,
	status TEXT NOT NULL,
	sealed_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_wealth_ta_day_result PRIMARY KEY (day_result_id),
	CONSTRAINT uq_ta_day_origin UNIQUE (account_id, origin_generation_id, trade_date),
	CONSTRAINT uq_ta_day_identity UNIQUE (account_id, day_result_id),
	CONSTRAINT uq_ta_day_date_identity UNIQUE (account_id, trade_date, day_result_id),
	CONSTRAINT fk_wealth_ta_day_result_account_id_wealth_ta_calculatio_62fe FOREIGN KEY(account_id, origin_generation_id) REFERENCES app.wealth_ta_calculation_generation (account_id, generation_id) ON DELETE RESTRICT,
	CONSTRAINT ck_wealth_ta_day_result_digest CHECK (octet_length(input_digest) = 32),
	CONSTRAINT ck_wealth_ta_day_result_seal CHECK ((status = 'SEALED' AND sealed_at IS NOT NULL) OR (status = 'BUILDING' AND sealed_at IS NULL))
)
    """,
    r"""
CREATE TABLE app.wealth_ta_position_state (
	account_id UUID NOT NULL,
	day_result_id UUID NOT NULL,
	ts_code TEXT NOT NULL,
	round_id UUID NOT NULL,
	opened_on DATE NOT NULL,
	closed_on DATE,
	quantity NUMERIC NOT NULL,
	remaining_buy_cost NUMERIC NOT NULL,
	cumulative_buy_input NUMERIC NOT NULL,
	cumulative_sell_net NUMERIC NOT NULL,
	CONSTRAINT pk_wealth_ta_position_state PRIMARY KEY (account_id, day_result_id, ts_code, round_id),
	CONSTRAINT fk_wealth_ta_position_state_account_id_wealth_ta_day_result FOREIGN KEY(account_id, day_result_id) REFERENCES app.wealth_ta_day_result (account_id, day_result_id) ON DELETE RESTRICT,
	CONSTRAINT ck_wealth_ta_position_state_quantity CHECK (quantity NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND quantity = trunc(quantity, 0) AND quantity >= 0),
	CONSTRAINT ck_wealth_ta_position_state_remaining_cost CHECK (remaining_buy_cost NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND remaining_buy_cost = trunc(remaining_buy_cost, 2) AND remaining_buy_cost >= 0),
	CONSTRAINT ck_wealth_ta_position_state_buy_input CHECK (cumulative_buy_input NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND cumulative_buy_input = trunc(cumulative_buy_input, 2) AND cumulative_buy_input >= 0),
	CONSTRAINT ck_wealth_ta_position_state_sell_net CHECK (cumulative_sell_net NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND cumulative_sell_net = trunc(cumulative_sell_net, 2)),
	CONSTRAINT ck_wealth_ta_position_state_cost_pool CHECK (remaining_buy_cost <= cumulative_buy_input)
)
    """,
    r"""
CREATE TABLE app.wealth_ta_closed_trade (
	account_id UUID NOT NULL,
	day_result_id UUID NOT NULL,
	sell_ledger_id UUID NOT NULL,
	sell_revision BIGINT NOT NULL,
	round_id UUID NOT NULL,
	quantity BIGINT NOT NULL,
	allocated_cost NUMERIC NOT NULL,
	net_proceeds NUMERIC NOT NULL,
	profit_amount NUMERIC NOT NULL,
	return_pct NUMERIC NOT NULL,
	CONSTRAINT pk_wealth_ta_closed_trade PRIMARY KEY (account_id, day_result_id, sell_ledger_id, sell_revision),
	CONSTRAINT fk_wealth_ta_closed_trade_account_id_wealth_ta_day_result FOREIGN KEY(account_id, day_result_id) REFERENCES app.wealth_ta_day_result (account_id, day_result_id) ON DELETE RESTRICT,
	CONSTRAINT fk_wealth_ta_closed_trade_account_id_wealth_ta_ledger_revision FOREIGN KEY(account_id, sell_ledger_id, sell_revision) REFERENCES app.wealth_ta_ledger_revision (account_id, ledger_id, revision) ON DELETE RESTRICT,
	CONSTRAINT ck_wealth_ta_closed_trade_quantity CHECK (quantity BETWEEN 1 AND 9007199254740991),
	CONSTRAINT ck_wealth_ta_closed_trade_cost CHECK (allocated_cost NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND allocated_cost = trunc(allocated_cost, 2) AND allocated_cost >= 0),
	CONSTRAINT ck_wealth_ta_closed_trade_net CHECK (net_proceeds NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND net_proceeds = trunc(net_proceeds, 2)),
	CONSTRAINT ck_wealth_ta_closed_trade_profit_precision CHECK (profit_amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND profit_amount = trunc(profit_amount, 2)),
	CONSTRAINT ck_wealth_ta_closed_trade_return_precision CHECK (return_pct NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND return_pct = trunc(return_pct, 2)),
	CONSTRAINT ck_wealth_ta_closed_trade_profit CHECK (profit_amount = net_proceeds - allocated_cost)
)
    """,
    r"""
ALTER TABLE app.wealth_ta_write_request ADD CONSTRAINT fk_ta_request_current_attempt FOREIGN KEY(owner_id, request_id, current_attempt_id) REFERENCES app.wealth_ta_write_attempt (owner_id, request_id, attempt_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
    """,
    r"""
ALTER TABLE app.wealth_ta_account ADD CONSTRAINT fk_ta_account_publication FOREIGN KEY(account_id, published_generation_id) REFERENCES app.wealth_ta_calculation_generation (account_id, generation_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
    """,
    r"""
ALTER TABLE app.wealth_ta_validation_candidate ADD CONSTRAINT fk_ta_candidate_request FOREIGN KEY(owner_id, request_id) REFERENCES app.wealth_ta_write_request (owner_id, request_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
    """,
    r"""
ALTER TABLE app.wealth_ta_account ADD CONSTRAINT fk_ta_account_initialization FOREIGN KEY(account_id, current_initialization_id) REFERENCES app.wealth_ta_initialization (account_id, initialization_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
    """,
    r"""
ALTER TABLE app.wealth_ta_write_scope ADD CONSTRAINT fk_ta_scope_holder FOREIGN KEY(owner_id, scope_key, holder_request_id) REFERENCES app.wealth_ta_write_request (owner_id, scope_key, request_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
    """,
    r"""
ALTER TABLE app.wealth_ta_write_request ADD CONSTRAINT fk_ta_request_candidate FOREIGN KEY(owner_id, request_id, candidate_id) REFERENCES app.wealth_ta_validation_candidate (owner_id, request_id, candidate_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
    """,
    r"""
ALTER TABLE app.wealth_ta_account ADD CONSTRAINT fk_ta_account_fee FOREIGN KEY(account_id, current_fee_version_id) REFERENCES app.wealth_ta_fee_version (account_id, fee_version_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
    """,
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(sa.text(statement))


def downgrade() -> None:
    raise RuntimeError("Trading assistant accounting and recovery evidence must be retained; destructive downgrade is not supported.")
