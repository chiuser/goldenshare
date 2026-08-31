"""add Wealth sector-analysis daily facts on HDD

Revision ID: 20260831_000168
Revises: 20260830_000167
Create Date: 2026-08-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260831_000168"
down_revision = "20260830_000167"
branch_labels = None
depends_on = None

_SCHEMA = "core_serving"
_TABLESPACE = "gs_raw_cold_hdd"
_TABLES = (
    "wealth_sector_analysis_publish_batch",
    "wealth_sector_momentum_daily",
    "wealth_sector_dual_momentum_daily",
    "wealth_sector_relative_rotation_daily",
    "wealth_sector_member_breadth_daily",
    "wealth_sector_member_ma_breadth_daily",
    "wealth_sector_price_volume_daily",
    "wealth_sector_daily_insight_summary",
    "wealth_sector_daily_insight_item",
)
_COMPARISON_IDENTITY_CHECK = """
(
  (comparison_scope='LEVEL_1' AND comparison_key='GLOBAL:L1' AND parent_sector_code IS NULL AND industry_level=1)
  OR (comparison_scope='LEVEL_2' AND comparison_key='GLOBAL:L2' AND parent_sector_code IS NULL AND industry_level=2)
  OR (comparison_scope='LEVEL_3' AND comparison_key='GLOBAL:L3' AND parent_sector_code IS NULL AND industry_level=3)
  OR (comparison_scope='LEVEL_1_CHILDREN' AND comparison_key='PARENT:L1:' || parent_sector_code AND parent_sector_code IS NOT NULL AND industry_level=2)
  OR (comparison_scope='LEVEL_2_CHILDREN' AND comparison_key='PARENT:L2:' || parent_sector_code AND parent_sector_code IS NOT NULL AND industry_level=3)
)
"""


def _assert_hdd_tablespace() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT pg_tablespace_location(oid), "
            "has_tablespace_privilege(current_user, oid, 'CREATE') "
            "FROM pg_tablespace WHERE spcname = :name"
        ),
        {"name": _TABLESPACE},
    ).one_or_none()
    if row is None:
        raise RuntimeError(f"板块分析每日事实要求 tablespace `{_TABLESPACE}`，禁止回退 SSD")
    location, can_create = row
    if not str(location or "").strip():
        raise RuntimeError(f"tablespace `{_TABLESPACE}` 缺少物理路径，禁止创建每日事实")
    if not bool(can_create):
        raise RuntimeError(f"当前数据库用户无权在 tablespace `{_TABLESPACE}` 创建对象")


def _identity_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("comparison_scope", sa.String(32), nullable=False),
        sa.Column("comparison_key", sa.String(64), nullable=False),
        sa.Column("parent_sector_code", sa.String(16)),
        sa.Column("sector_code", sa.String(16), nullable=False),
        sa.Column("sector_name", sa.String(128), nullable=False),
        sa.Column("industry_level", sa.Integer(), nullable=False),
        sa.Column("hierarchy_path", sa.String(512), nullable=False),
    )


def _formula_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("formula_key", sa.String(64), nullable=False),
        sa.Column("formula_version", sa.Integer(), nullable=False),
        sa.Column("calculation_status", sa.String(16), nullable=False),
        sa.Column("missing_reason", sa.String(64), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _create_table(name: str, *columns: sa.SchemaItem) -> None:
    op.create_table(
        name,
        *columns,
        schema=_SCHEMA,
        postgresql_tablespace=_TABLESPACE,
    )


def _add_primary_key(name: str, columns: str) -> None:
    op.execute(
        f"ALTER TABLE {_SCHEMA}.{name} ADD CONSTRAINT pk_{name} "
        f"PRIMARY KEY ({columns}) USING INDEX TABLESPACE {_TABLESPACE}"
    )


def _add_batch_fk(table: str) -> None:
    op.execute(
        f"ALTER TABLE {_SCHEMA}.{table} ADD CONSTRAINT fk_{table}_batch_date "
        f"FOREIGN KEY (batch_id, trade_date) REFERENCES {_SCHEMA}.wealth_sector_analysis_publish_batch "
        "(batch_id, trade_date)"
    )


def _index(name: str, table: str, columns: str, *, unique: bool = False, where: str | None = None) -> None:
    unique_sql = "UNIQUE " if unique else ""
    where_sql = f" WHERE {where}" if where else ""
    op.execute(
        f"CREATE {unique_sql}INDEX {name} ON {_SCHEMA}.{table} ({columns}) "
        f"TABLESPACE {_TABLESPACE}{where_sql}"
    )


def _assert_catalog_on_hdd() -> None:
    rows = op.get_bind().execute(
        sa.text(
            "WITH heaps AS ("
            " SELECT c.oid, c.reltoastrelid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace"
            " WHERE n.nspname=:schema AND c.relname = ANY(:tables) AND c.relkind='r'"
            "), relations AS ("
            " SELECT oid FROM heaps UNION SELECT reltoastrelid FROM heaps WHERE reltoastrelid <> 0"
            " UNION SELECT i.indexrelid FROM pg_index i JOIN heaps h ON h.oid=i.indrelid"
            " UNION SELECT i.indexrelid FROM pg_index i JOIN heaps h ON h.reltoastrelid=i.indrelid WHERE h.reltoastrelid <> 0"
            ") SELECT c.relname, c.relkind, COALESCE(ts.spcname, dbts.spcname) AS effective_tablespace,"
            " pg_tablespace_location(COALESCE(ts.oid, dbts.oid)) AS location"
            " FROM relations r JOIN pg_class c ON c.oid=r.oid"
            " CROSS JOIN pg_database d LEFT JOIN pg_tablespace ts ON ts.oid=NULLIF(c.reltablespace,0)"
            " JOIN pg_tablespace dbts ON dbts.oid=d.dattablespace"
            " WHERE d.datname=current_database() ORDER BY c.relkind,c.relname"
        ),
        {"schema": _SCHEMA, "tables": list(_TABLES)},
    ).all()
    heap_names = {row.relname for row in rows if row.relkind == "r" and row.relname in _TABLES}
    if heap_names != set(_TABLES):
        raise RuntimeError("板块分析每日事实 catalog 验收缺少目标 heap")
    mismatches = [
        (row.relname, row.relkind, row.effective_tablespace, row.location)
        for row in rows
        if row.effective_tablespace != _TABLESPACE or not str(row.location or "").strip()
    ]
    if mismatches:
        raise RuntimeError(f"板块分析每日事实存在未落 HDD 的物理对象: {mismatches}")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    _assert_hdd_tablespace()

    _create_table(
        "wealth_sector_analysis_publish_batch",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("previous_trade_date", sa.Date()),
        sa.Column("previous_batch_id", sa.Uuid()),
        sa.Column("hierarchy_version", sa.String(128), nullable=False),
        sa.Column("formula_bundle_version", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.CHAR(64), nullable=False),
        sa.Column("plan_hash", sa.CHAR(64), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("source_dates_json", postgresql.JSONB(), nullable=False),
        sa.Column("source_row_counts_json", postgresql.JSONB(), nullable=False),
        sa.Column("expected_fact_counts_json", postgresql.JSONB(), nullable=False),
        sa.Column("actual_fact_counts_json", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason_code", sa.String(64)),
        sa.CheckConstraint("status IN ('BUILDING','PUBLISHED','SUPERSEDED','FAILED')", name="ck_wealth_sector_analysis_batch_status"),
        sa.CheckConstraint("source_hash ~ '^[0-9a-f]{64}$' AND plan_hash ~ '^[0-9a-f]{64}$' AND content_hash ~ '^[0-9a-f]{64}$'", name="ck_wealth_sector_analysis_batch_hashes"),
        sa.CheckConstraint(
            "previous_batch_id IS NULL OR previous_trade_date IS NOT NULL",
            name="ck_wealth_sector_analysis_previous_binding",
        ),
    )
    _add_primary_key("wealth_sector_analysis_publish_batch", "batch_id")
    op.execute(
        f"ALTER TABLE {_SCHEMA}.wealth_sector_analysis_publish_batch ADD CONSTRAINT "
        f"uq_wealth_sector_analysis_batch_id_trade_date UNIQUE (batch_id, trade_date) "
        f"USING INDEX TABLESPACE {_TABLESPACE}"
    )
    op.execute(
        f"ALTER TABLE {_SCHEMA}.wealth_sector_analysis_publish_batch ADD CONSTRAINT "
        "fk_wealth_sector_analysis_previous_batch_date FOREIGN KEY (previous_batch_id,previous_trade_date) "
        f"REFERENCES {_SCHEMA}.wealth_sector_analysis_publish_batch (batch_id,trade_date)"
    )
    _index("uq_wealth_sector_analysis_one_published_per_date", "wealth_sector_analysis_publish_batch", "trade_date", unique=True, where="status='PUBLISHED'")
    _index("uq_wealth_sector_analysis_success_content", "wealth_sector_analysis_publish_batch", "trade_date,plan_hash,content_hash", unique=True, where="status IN ('PUBLISHED','SUPERSEDED')")
    _index("idx_wealth_sector_analysis_batch_status_trade_published", "wealth_sector_analysis_publish_batch", "status,trade_date DESC,published_at DESC")
    _index("idx_wealth_sector_analysis_batch_hierarchy_trade", "wealth_sector_analysis_publish_batch", "hierarchy_version,trade_date")

    _create_table(
        "wealth_sector_momentum_daily",
        *_identity_columns(),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("return_pct", sa.Numeric(18, 6)),
        sa.Column("strength_rank", sa.Integer()),
        sa.Column("rankable_count", sa.Integer()),
        sa.Column("percentile", sa.Numeric(8, 4)),
        *_formula_columns(),
        sa.CheckConstraint("period IN (1,5,10,20,30)", name="ck_wealth_sector_momentum_period"),
        sa.CheckConstraint(_COMPARISON_IDENTITY_CHECK, name="ck_wealth_sector_momentum_comparison"),
    )
    _add_primary_key("wealth_sector_momentum_daily", "batch_id,comparison_scope,comparison_key,sector_code,period")
    _add_batch_fk("wealth_sector_momentum_daily")
    _index("idx_wealth_sector_momentum_trade_scope_period_rank", "wealth_sector_momentum_daily", "trade_date,comparison_scope,comparison_key,period,strength_rank,sector_code")

    _create_table(
        "wealth_sector_dual_momentum_daily",
        *_identity_columns(),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("return_pct", sa.Numeric(18, 6)),
        sa.Column("strength_rank", sa.Integer()),
        sa.Column("rankable_count", sa.Integer()),
        sa.Column("percentile", sa.Numeric(8, 4)),
        sa.Column("absolute_status", sa.String(32), nullable=False),
        sa.Column("coordinate_status", sa.String(32), nullable=False),
        *[sa.Column(f"{prefix}_{threshold}", sa.String(32), nullable=False) for threshold in (70,80,90) for prefix in ("relative_status","qualification_status","display_status")],
        sa.Column("minimum_group_size", sa.Integer(), nullable=False),
        *_formula_columns(),
        sa.CheckConstraint("period IN (5,10,20,30)", name="ck_wealth_sector_dual_period"),
        sa.CheckConstraint("minimum_group_size=3", name="ck_wealth_sector_dual_min_group"),
        sa.CheckConstraint(_COMPARISON_IDENTITY_CHECK, name="ck_wealth_sector_dual_comparison"),
    )
    _add_primary_key("wealth_sector_dual_momentum_daily", "batch_id,comparison_scope,comparison_key,sector_code,period")
    _add_batch_fk("wealth_sector_dual_momentum_daily")
    _index("idx_wealth_sector_dual_trade_scope_period_q80", "wealth_sector_dual_momentum_daily", "trade_date,comparison_scope,comparison_key,period,qualification_status_80,sector_code")

    _create_table(
        "wealth_sector_relative_rotation_daily",
        *_identity_columns(),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("comparison_trade_date", sa.Date(), nullable=False),
        sa.Column("return_pct", sa.Numeric(18, 6)), sa.Column("strength_rank", sa.Integer()), sa.Column("rankable_count", sa.Integer()), sa.Column("percentile", sa.Numeric(8, 4)),
        sa.Column("comparison_return_pct", sa.Numeric(18, 6)), sa.Column("comparison_strength_rank", sa.Integer()), sa.Column("comparison_rankable_count", sa.Integer()), sa.Column("comparison_percentile", sa.Numeric(8, 4)),
        sa.Column("percentile_delta_5d", sa.Numeric(8, 4)),
        sa.Column("rotation_status", sa.String(32), nullable=False), sa.Column("coordinate_status", sa.String(32), nullable=False), sa.Column("group_interpretation", sa.String(32), nullable=False),
        sa.Column("current_missing_reason", sa.String(64)), sa.Column("comparison_missing_reason", sa.String(64)), sa.Column("minimum_group_size", sa.Integer(), nullable=False),
        *_formula_columns(),
        sa.CheckConstraint("period IN (5,10,20,30)", name="ck_wealth_sector_rotation_period"),
        sa.CheckConstraint("minimum_group_size=3", name="ck_wealth_sector_rotation_min_group"),
        sa.CheckConstraint(_COMPARISON_IDENTITY_CHECK, name="ck_wealth_sector_rotation_comparison"),
    )
    _add_primary_key("wealth_sector_relative_rotation_daily", "batch_id,comparison_scope,comparison_key,sector_code,period")
    _add_batch_fk("wealth_sector_relative_rotation_daily")
    _index("idx_wealth_sector_rotation_trade_scope_period_status", "wealth_sector_relative_rotation_daily", "trade_date,comparison_scope,comparison_key,period,rotation_status,sector_code")

    _create_member_tables()
    _create_insight_tables()
    _assert_catalog_on_hdd()


def _create_member_tables() -> None:
    breadth_columns: list[sa.SchemaItem] = [*_identity_columns(), sa.Column("source_member_count", sa.Integer(), nullable=False)]
    breadth_columns += [
        sa.Column("member_calculable_count", sa.Integer(), nullable=False), sa.Column("member_coverage_pct", sa.Numeric(8,4), nullable=False), sa.Column("member_qualification", sa.String(16), nullable=False), sa.Column("member_reason_codes", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("member_up_count", sa.Integer(), nullable=False), sa.Column("member_flat_count", sa.Integer(), nullable=False), sa.Column("member_down_count", sa.Integer(), nullable=False), sa.Column("member_up_pct", sa.Numeric(8,4)), sa.Column("member_flat_pct", sa.Numeric(8,4)), sa.Column("member_down_pct", sa.Numeric(8,4)),
    ]
    for direction in ("up", "down"):
        breadth_columns += [sa.Column(f"member_{direction}_rank", sa.Integer()), sa.Column(f"member_{direction}_rankable_count", sa.Integer()), sa.Column(f"member_{direction}_percentile", sa.Numeric(8,4))]
    breadth_columns += [
        sa.Column("turnover_calculable_count", sa.Integer(), nullable=False), sa.Column("turnover_coverage_pct", sa.Numeric(8,4), nullable=False), sa.Column("turnover_qualification", sa.String(16), nullable=False), sa.Column("turnover_reason_codes", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("turnover_up_count", sa.Integer(), nullable=False), sa.Column("turnover_flat_count", sa.Integer(), nullable=False), sa.Column("turnover_down_count", sa.Integer(), nullable=False),
        sa.Column("turnover_up_amount", sa.Numeric(24,6), nullable=False), sa.Column("turnover_flat_amount", sa.Numeric(24,6), nullable=False), sa.Column("turnover_down_amount", sa.Numeric(24,6), nullable=False),
        sa.Column("turnover_up_pct", sa.Numeric(8,4)), sa.Column("turnover_flat_pct", sa.Numeric(8,4)), sa.Column("turnover_down_pct", sa.Numeric(8,4)),
    ]
    for direction in ("up", "down"):
        breadth_columns += [sa.Column(f"turnover_{direction}_rank", sa.Integer()), sa.Column(f"turnover_{direction}_rankable_count", sa.Integer()), sa.Column(f"turnover_{direction}_percentile", sa.Numeric(8,4))]
    breadth_columns += list(_formula_columns())
    breadth_columns.append(sa.CheckConstraint(_COMPARISON_IDENTITY_CHECK, name="ck_wealth_sector_member_breadth_comparison"))
    _create_table("wealth_sector_member_breadth_daily", *breadth_columns)
    _add_primary_key("wealth_sector_member_breadth_daily", "batch_id,comparison_scope,comparison_key,sector_code")
    _add_batch_fk("wealth_sector_member_breadth_daily")
    for metric in ("member_up", "member_down", "turnover_up", "turnover_down"):
        _index(f"idx_wealth_sector_{metric}_rank", "wealth_sector_member_breadth_daily", f"trade_date,comparison_scope,comparison_key,{metric}_rank,sector_code")

    _create_table(
        "wealth_sector_member_ma_breadth_daily",
        *_identity_columns(), sa.Column("ma_period", sa.Integer(), nullable=False), sa.Column("source_member_count", sa.Integer(), nullable=False), sa.Column("calculable_count", sa.Integer(), nullable=False), sa.Column("coverage_pct", sa.Numeric(8,4), nullable=False), sa.Column("qualification", sa.String(16), nullable=False), sa.Column("reason_codes", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("above_count", sa.Integer(), nullable=False), sa.Column("equal_count", sa.Integer(), nullable=False), sa.Column("below_count", sa.Integer(), nullable=False), sa.Column("above_pct", sa.Numeric(8,4)), sa.Column("equal_pct", sa.Numeric(8,4)), sa.Column("below_pct", sa.Numeric(8,4)),
        sa.Column("up_rank", sa.Integer()), sa.Column("up_rankable_count", sa.Integer()), sa.Column("up_percentile", sa.Numeric(8,4)), sa.Column("down_rank", sa.Integer()), sa.Column("down_rankable_count", sa.Integer()), sa.Column("down_percentile", sa.Numeric(8,4)),
        *_formula_columns(), sa.CheckConstraint("ma_period IN (5,10,15,20,30,60)", name="ck_wealth_sector_member_ma_period"),
        sa.CheckConstraint(_COMPARISON_IDENTITY_CHECK, name="ck_wealth_sector_member_ma_comparison"),
    )
    _add_primary_key("wealth_sector_member_ma_breadth_daily", "batch_id,comparison_scope,comparison_key,sector_code,ma_period")
    _add_batch_fk("wealth_sector_member_ma_breadth_daily")
    for direction in ("up", "down"):
        _index(f"idx_wealth_sector_member_ma_{direction}_rank", "wealth_sector_member_ma_breadth_daily", f"trade_date,comparison_scope,comparison_key,ma_period,{direction}_rank,sector_code")

    _create_table(
        "wealth_sector_price_volume_daily",
        *_identity_columns(), sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("price_momentum_pct", sa.Numeric(18,6)), sa.Column("price_missing_reason", sa.String(64)), sa.Column("price_rank", sa.Integer()), sa.Column("price_rankable_count", sa.Integer()), sa.Column("price_percentile", sa.Numeric(8,4)),
        sa.Column("amount_activity_pct", sa.Numeric(18,6)), sa.Column("amount_missing_reason", sa.String(64)), sa.Column("amount_rank", sa.Integer()), sa.Column("amount_rankable_count", sa.Integer()), sa.Column("amount_percentile", sa.Numeric(8,4)), sa.Column("distribution_state", sa.String(32)),
        *_formula_columns(), sa.CheckConstraint("period IN (1,5,10,20,30)", name="ck_wealth_sector_price_volume_period"),
        sa.CheckConstraint(_COMPARISON_IDENTITY_CHECK, name="ck_wealth_sector_price_volume_comparison"),
    )
    _add_primary_key("wealth_sector_price_volume_daily", "batch_id,comparison_scope,comparison_key,sector_code,period")
    _add_batch_fk("wealth_sector_price_volume_daily")
    _index("idx_wealth_sector_price_volume_price_rank", "wealth_sector_price_volume_daily", "trade_date,comparison_scope,comparison_key,period,price_rank,sector_code")
    _index("idx_wealth_sector_price_volume_amount_rank", "wealth_sector_price_volume_daily", "trade_date,comparison_scope,comparison_key,period,amount_rank,sector_code")
    _index("idx_wealth_sector_price_volume_state", "wealth_sector_price_volume_daily", "trade_date,comparison_scope,comparison_key,period,distribution_state,sector_code")


def _create_insight_tables() -> None:
    summary_count_names = (
        "sector_count", "calculable_count", "missing_count", "up_count", "down_count", "flat_count",
        "dual_momentum_count_20d_80", "leading_improving_count_20d_5d", "price_volume_joint_count_20d", "breadth_up_share_above_50_count",
        "missing_history_count", "missing_date_count", "missing_price_count", "missing_member_count", "missing_amount_count", "missing_adj_factor_count", "missing_group_size_count", "missing_coverage_count", "missing_previous_batch_count", "missing_other_count",
    )
    _create_table(
        "wealth_sector_daily_insight_summary",
        sa.Column("batch_id", sa.Uuid(), nullable=False), sa.Column("trade_date", sa.Date(), nullable=False), sa.Column("industry_level", sa.Integer(), nullable=False),
        *[sa.Column(name, sa.Integer(), nullable=False) for name in summary_count_names[:6]],
        sa.Column("median_change_pct_1d", sa.Numeric(18,6)),
        *[sa.Column(name, sa.Integer(), nullable=False) for name in summary_count_names[6:]],
        sa.CheckConstraint("industry_level BETWEEN 1 AND 3", name="ck_wealth_sector_insight_summary_level"),
        sa.CheckConstraint("sector_count=calculable_count+missing_count", name="ck_wealth_sector_insight_summary_counts"),
    )
    _add_primary_key("wealth_sector_daily_insight_summary", "batch_id,industry_level")
    _add_batch_fk("wealth_sector_daily_insight_summary")

    _create_table(
        "wealth_sector_daily_insight_item",
        sa.Column("batch_id", sa.Uuid(), nullable=False), sa.Column("trade_date", sa.Date(), nullable=False), sa.Column("industry_level", sa.Integer(), nullable=False), sa.Column("category", sa.String(32), nullable=False), sa.Column("sector_code", sa.String(16), nullable=False),
        sa.Column("stable_order", sa.Integer(), nullable=False), sa.Column("event_type", sa.String(64), nullable=False), sa.Column("sector_name", sa.String(128), nullable=False), sa.Column("hierarchy_path", sa.String(512), nullable=False),
        sa.Column("return_pct_1d", sa.Numeric(18,6)), sa.Column("return_pct_5d", sa.Numeric(18,6)), sa.Column("return_pct_20d", sa.Numeric(18,6)),
        sa.Column("current_rank_20d", sa.Integer()), sa.Column("current_rankable_count_20d", sa.Integer()), sa.Column("current_percentile_20d", sa.Numeric(8,4)), sa.Column("previous_rank_20d", sa.Integer()), sa.Column("previous_rankable_count_20d", sa.Integer()), sa.Column("previous_percentile_20d", sa.Numeric(8,4)), sa.Column("rank_change", sa.Integer()), sa.Column("percentile_change_pp", sa.Numeric(8,4)),
        *[sa.Column(name, sa.String(32)) for name in ("price_volume_state_current","price_volume_state_previous","dual_qualification_20d_80_current","dual_qualification_20d_80_previous","rotation_status_20d_current","rotation_status_20d_previous")],
        *[sa.Column(name, sa.Numeric(8,4)) for name in ("member_up_pct_current","member_up_pct_previous","turnover_up_pct_current","turnover_up_pct_previous","ma20_above_pct_current","ma20_above_pct_previous")],
        sa.Column("primary_evidence_type", sa.String(64)), sa.Column("secondary_evidence_type_1", sa.String(64)), sa.Column("secondary_evidence_type_2", sa.String(64)), sa.Column("template_key", sa.String(64), nullable=False), sa.Column("template_version", sa.String(64), nullable=False), sa.Column("rendered_text", sa.Text(), nullable=False),
        sa.CheckConstraint("category IN ('HEAD_GAINER','HEAD_LOSER','STRENGTHENING','WEAKENING')", name="ck_wealth_sector_insight_item_category"),
    )
    _add_primary_key("wealth_sector_daily_insight_item", "batch_id,industry_level,category,sector_code")
    _add_batch_fk("wealth_sector_daily_insight_item")
    _index("idx_wealth_sector_insight_item_stable_order", "wealth_sector_daily_insight_item", "batch_id,industry_level,category,stable_order,sector_code")


def downgrade() -> None:
    raise RuntimeError("板块分析每日事实属于已发布业务证据，不支持自动 downgrade 删除。")
