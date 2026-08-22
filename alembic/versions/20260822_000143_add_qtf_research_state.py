"""add QTF research and revision state

Revision ID: 20260822_000143
Revises: 20260822_000142
Create Date: 2026-08-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260822_000143"
down_revision = "20260822_000142"
branch_labels = None
depends_on = None

_SCHEMA = "qtf"


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS qtf"))
    op.create_table(
        "research",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("research_key", sa.String(length=96), nullable=False),
        sa.Column("create_request_key", sa.String(length=96), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("template_key", sa.String(length=96), nullable=False),
        sa.Column("capability_key", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="DRAFT", nullable=False),
        sa.Column("latest_revision_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status in ('DRAFT', 'ACTIVE', 'ENDED')",
            name=op.f("ck_research_qtf_research_status_valid"),
        ),
        sa.CheckConstraint(
            "latest_revision_no >= 1",
            name=op.f("ck_research_qtf_research_latest_revision_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research")),
        sa.UniqueConstraint("research_key", name="uq_qtf_research_research_key"),
        sa.UniqueConstraint("create_request_key", name="uq_qtf_research_create_request_key"),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_qtf_research_status_updated_at",
        "research",
        ["status", sa.text("updated_at DESC")],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "experiment_revision",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("revision_key", sa.String(length=96), nullable=False),
        sa.Column("request_key", sa.String(length=96), nullable=False),
        sa.Column("research_id", sa.BigInteger(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="DRAFT", nullable=False),
        sa.Column("problem_statement", sa.Text(), nullable=False),
        sa.Column("success_definition_json", sa.JSON(), nullable=False),
        sa.Column("non_goals_json", sa.JSON(), nullable=False),
        sa.Column("source_contract_json", sa.JSON(), nullable=False),
        sa.Column("universe_spec_json", sa.JSON(), nullable=False),
        sa.Column("comparison_spec_json", sa.JSON(), nullable=False),
        sa.Column("formula_key", sa.String(length=96), nullable=False),
        sa.Column("formula_version", sa.String(length=96), nullable=False),
        sa.Column("parameter_schema_key", sa.String(length=96), nullable=False),
        sa.Column("parameter_schema_version", sa.String(length=96), nullable=False),
        sa.Column("effective_params_json", sa.JSON(), nullable=False),
        sa.Column("validation_spec_json", sa.JSON(), nullable=False),
        sa.Column("budget_json", sa.JSON(), nullable=False),
        sa.Column("draft_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("revision_hash", sa.String(length=64), nullable=True),
        sa.Column("frozen_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status in ('DRAFT', 'FROZEN', 'RETIRED')",
            name=op.f("ck_experiment_revision_qtf_experiment_revision_status_valid"),
        ),
        sa.CheckConstraint(
            "revision_no >= 1",
            name=op.f("ck_experiment_revision_qtf_experiment_revision_revision_no_positive"),
        ),
        sa.CheckConstraint(
            "draft_version >= 1",
            name=op.f("ck_experiment_revision_qtf_experiment_revision_draft_version_positive"),
        ),
        sa.CheckConstraint(
            "revision_hash is null or (length(revision_hash) = 64 and revision_hash = lower(revision_hash))",
            name=op.f("ck_experiment_revision_qtf_experiment_revision_hash_shape"),
        ),
        sa.CheckConstraint(
            "(status = 'FROZEN' and revision_hash is not null and frozen_by_user_id is not null and frozen_at is not null) "
            "or (status in ('DRAFT', 'RETIRED') and revision_hash is null "
            "and frozen_by_user_id is null and frozen_at is null)",
            name=op.f("ck_experiment_revision_qtf_experiment_revision_frozen_fields_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"],
            ["qtf.experiment_revision.id"],
            name=op.f("fk_experiment_revision_parent_revision_id_experiment_revision"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["research_id"],
            ["qtf.research.id"],
            name=op.f("fk_experiment_revision_research_id_research"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiment_revision")),
        sa.UniqueConstraint("revision_key", name="uq_qtf_experiment_revision_revision_key"),
        sa.UniqueConstraint("request_key", name="uq_qtf_experiment_revision_request_key"),
        sa.UniqueConstraint(
            "research_id",
            "revision_no",
            name="uq_qtf_experiment_revision_research_revision_no",
        ),
        sa.UniqueConstraint("revision_hash", name="uq_qtf_experiment_revision_revision_hash"),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_qtf_experiment_revision_research_status",
        "experiment_revision",
        ["research_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.drop_index(
        "idx_qtf_experiment_revision_research_status",
        table_name="experiment_revision",
        schema=_SCHEMA,
    )
    op.drop_table("experiment_revision", schema=_SCHEMA)
    op.drop_index(
        "idx_qtf_research_status_updated_at",
        table_name="research",
        schema=_SCHEMA,
    )
    op.drop_table("research", schema=_SCHEMA)
    op.execute(sa.text("DROP SCHEMA qtf"))
