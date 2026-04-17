"""add auth registration and rbac foundation"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "20260417_000064"
down_revision = "20260417_000063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("account_state", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        schema="app",
    )
    op.add_column("app_user", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True), schema="app")
    op.add_column("app_user", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True), schema="app")
    op.add_column(
        "app_user",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema="app",
    )
    op.add_column("app_user", sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True), schema="app")
    op.add_column("app_user", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True), schema="app")
    op.create_index("idx_app_user_account_state", "app_user", ["account_state"], schema="app")

    op.create_table(
        "auth_role",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=255)),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("key", name="uq_auth_role_key"),
        schema="app",
    )
    op.create_index("idx_auth_role_is_system", "auth_role", ["is_system"], schema="app")

    op.create_table(
        "auth_permission",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("key", name="uq_auth_permission_key"),
        schema="app",
    )
    op.create_index("idx_auth_permission_key", "auth_permission", ["key"], schema="app")

    op.create_table(
        "auth_user_role",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_index("idx_auth_user_role_user_id", "auth_user_role", ["user_id"], schema="app")
    op.create_index("idx_auth_user_role_role_key", "auth_user_role", ["role_key"], schema="app")
    op.create_index(
        "uq_auth_user_role_user_role",
        "auth_user_role",
        ["user_id", "role_key"],
        unique=True,
        schema="app",
    )

    op.create_table(
        "auth_role_permission",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("permission_key", sa.String(length=64), nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_index("idx_auth_role_permission_role_key", "auth_role_permission", ["role_key"], schema="app")
    op.create_index(
        "idx_auth_role_permission_permission_key",
        "auth_role_permission",
        ["permission_key"],
        schema="app",
    )
    op.create_index(
        "uq_auth_role_permission_role_permission",
        "auth_role_permission",
        ["role_key", "permission_key"],
        unique=True,
        schema="app",
    )

    op.create_table(
        "auth_refresh_token",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.String(length=64)),
        sa.Column("replaced_by_id", sa.Integer()),
        sa.Column("ip_address", sa.String(length=64)),
        sa.Column("user_agent", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_index("idx_auth_refresh_token_user_id", "auth_refresh_token", ["user_id"], schema="app")
    op.create_index("idx_auth_refresh_token_status", "auth_refresh_token", ["status"], schema="app")
    op.create_index("idx_auth_refresh_token_expires_at", "auth_refresh_token", ["expires_at"], schema="app")
    op.create_index("uq_auth_refresh_token_token_hash", "auth_refresh_token", ["token_hash"], unique=True, schema="app")

    op.create_table(
        "auth_action_token",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_index("idx_auth_action_token_user_id", "auth_action_token", ["user_id"], schema="app")
    op.create_index("idx_auth_action_token_action_type", "auth_action_token", ["action_type"], schema="app")
    op.create_index("idx_auth_action_token_expires_at", "auth_action_token", ["expires_at"], schema="app")
    op.create_index("uq_auth_action_token_token_hash", "auth_action_token", ["token_hash"], unique=True, schema="app")

    op.create_table(
        "auth_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer()),
        sa.Column("username_snapshot", sa.String(length=64)),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_status", sa.String(length=16), nullable=False, server_default=sa.text("'success'")),
        sa.Column("ip_address", sa.String(length=64)),
        sa.Column("user_agent", sa.String(length=255)),
        sa.Column("detail_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        schema="app",
    )
    op.create_index("idx_auth_audit_log_user_id_occurred_at", "auth_audit_log", ["user_id", "occurred_at"], schema="app")
    op.create_index(
        "idx_auth_audit_log_event_type_occurred_at",
        "auth_audit_log",
        ["event_type", "occurred_at"],
        schema="app",
    )

    op.create_table(
        "auth_invite_code",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("code_hint", sa.String(length=16), nullable=False),
        sa.Column("role_key", sa.String(length=64), nullable=False, server_default=sa.text("'viewer'")),
        sa.Column("assigned_email", sa.String(length=255)),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.Column("note", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_index("idx_auth_invite_code_role_key", "auth_invite_code", ["role_key"], schema="app")
    op.create_index("idx_auth_invite_code_expires_at", "auth_invite_code", ["expires_at"], schema="app")
    op.create_index("idx_auth_invite_code_disabled_at", "auth_invite_code", ["disabled_at"], schema="app")
    op.create_index("uq_auth_invite_code_hash", "auth_invite_code", ["code_hash"], unique=True, schema="app")

    now = datetime.now(timezone.utc)
    role_table = sa.table(
        "auth_role",
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("is_system", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    permission_table = sa.table(
        "auth_permission",
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    role_permission_table = sa.table(
        "auth_role_permission",
        sa.column("role_key", sa.String()),
        sa.column("permission_key", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    op.bulk_insert(
        role_table,
        [
            {"key": "admin", "name": "管理员", "description": "平台管理员", "is_system": True, "created_at": now, "updated_at": now},
            {"key": "operator", "name": "操作员", "description": "运维操作角色", "is_system": True, "created_at": now, "updated_at": now},
            {"key": "analyst", "name": "分析员", "description": "只读分析角色", "is_system": True, "created_at": now, "updated_at": now},
            {"key": "viewer", "name": "访客", "description": "基础查看角色", "is_system": True, "created_at": now, "updated_at": now},
        ],
    )
    op.bulk_insert(
        permission_table,
        [
            {"key": "ops.read", "name": "运维查看", "description": "查看运维数据", "created_at": now, "updated_at": now},
            {"key": "ops.write", "name": "运维配置", "description": "修改运维配置", "created_at": now, "updated_at": now},
            {"key": "ops.execute", "name": "运维执行", "description": "执行运维动作", "created_at": now, "updated_at": now},
            {"key": "quote.read", "name": "行情查看", "description": "读取行情数据", "created_at": now, "updated_at": now},
            {"key": "share.read", "name": "共享页查看", "description": "读取共享市场页面数据", "created_at": now, "updated_at": now},
            {"key": "user.manage", "name": "用户管理", "description": "管理用户和角色", "created_at": now, "updated_at": now},
            {"key": "auth.audit.read", "name": "认证审计查看", "description": "查看认证审计日志", "created_at": now, "updated_at": now},
        ],
    )
    op.bulk_insert(
        role_permission_table,
        [
            {"role_key": "admin", "permission_key": "ops.read", "created_at": now, "updated_at": now},
            {"role_key": "admin", "permission_key": "ops.write", "created_at": now, "updated_at": now},
            {"role_key": "admin", "permission_key": "ops.execute", "created_at": now, "updated_at": now},
            {"role_key": "admin", "permission_key": "quote.read", "created_at": now, "updated_at": now},
            {"role_key": "admin", "permission_key": "share.read", "created_at": now, "updated_at": now},
            {"role_key": "admin", "permission_key": "user.manage", "created_at": now, "updated_at": now},
            {"role_key": "admin", "permission_key": "auth.audit.read", "created_at": now, "updated_at": now},
            {"role_key": "operator", "permission_key": "ops.read", "created_at": now, "updated_at": now},
            {"role_key": "operator", "permission_key": "ops.write", "created_at": now, "updated_at": now},
            {"role_key": "operator", "permission_key": "ops.execute", "created_at": now, "updated_at": now},
            {"role_key": "analyst", "permission_key": "quote.read", "created_at": now, "updated_at": now},
            {"role_key": "analyst", "permission_key": "share.read", "created_at": now, "updated_at": now},
            {"role_key": "viewer", "permission_key": "quote.read", "created_at": now, "updated_at": now},
        ],
    )

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            """
            INSERT OR IGNORE INTO app.auth_user_role (user_id, role_key, created_at, updated_at)
            SELECT id,
                   CASE WHEN is_admin = 1 THEN 'admin' ELSE 'viewer' END,
                   CURRENT_TIMESTAMP,
                   CURRENT_TIMESTAMP
            FROM app.app_user
            """
        )
    else:
        op.execute(
            """
            INSERT INTO app.auth_user_role (user_id, role_key, created_at, updated_at)
            SELECT id,
                   CASE WHEN is_admin THEN 'admin' ELSE 'viewer' END,
                   NOW(),
                   NOW()
            FROM app.app_user
            ON CONFLICT (user_id, role_key) DO NOTHING
            """
        )


def downgrade() -> None:
    op.drop_index("uq_auth_invite_code_hash", table_name="auth_invite_code", schema="app")
    op.drop_index("idx_auth_invite_code_disabled_at", table_name="auth_invite_code", schema="app")
    op.drop_index("idx_auth_invite_code_expires_at", table_name="auth_invite_code", schema="app")
    op.drop_index("idx_auth_invite_code_role_key", table_name="auth_invite_code", schema="app")
    op.drop_table("auth_invite_code", schema="app")

    op.drop_index("idx_auth_audit_log_event_type_occurred_at", table_name="auth_audit_log", schema="app")
    op.drop_index("idx_auth_audit_log_user_id_occurred_at", table_name="auth_audit_log", schema="app")
    op.drop_table("auth_audit_log", schema="app")

    op.drop_index("uq_auth_action_token_token_hash", table_name="auth_action_token", schema="app")
    op.drop_index("idx_auth_action_token_expires_at", table_name="auth_action_token", schema="app")
    op.drop_index("idx_auth_action_token_action_type", table_name="auth_action_token", schema="app")
    op.drop_index("idx_auth_action_token_user_id", table_name="auth_action_token", schema="app")
    op.drop_table("auth_action_token", schema="app")

    op.drop_index("uq_auth_refresh_token_token_hash", table_name="auth_refresh_token", schema="app")
    op.drop_index("idx_auth_refresh_token_expires_at", table_name="auth_refresh_token", schema="app")
    op.drop_index("idx_auth_refresh_token_status", table_name="auth_refresh_token", schema="app")
    op.drop_index("idx_auth_refresh_token_user_id", table_name="auth_refresh_token", schema="app")
    op.drop_table("auth_refresh_token", schema="app")

    op.drop_index("uq_auth_role_permission_role_permission", table_name="auth_role_permission", schema="app")
    op.drop_index("idx_auth_role_permission_permission_key", table_name="auth_role_permission", schema="app")
    op.drop_index("idx_auth_role_permission_role_key", table_name="auth_role_permission", schema="app")
    op.drop_table("auth_role_permission", schema="app")

    op.drop_index("uq_auth_user_role_user_role", table_name="auth_user_role", schema="app")
    op.drop_index("idx_auth_user_role_role_key", table_name="auth_user_role", schema="app")
    op.drop_index("idx_auth_user_role_user_id", table_name="auth_user_role", schema="app")
    op.drop_table("auth_user_role", schema="app")

    op.drop_index("idx_auth_permission_key", table_name="auth_permission", schema="app")
    op.drop_table("auth_permission", schema="app")

    op.drop_index("idx_auth_role_is_system", table_name="auth_role", schema="app")
    op.drop_table("auth_role", schema="app")

    op.drop_index("idx_app_user_account_state", table_name="app_user", schema="app")
    op.drop_column("app_user", "locked_until", schema="app")
    op.drop_column("app_user", "last_failed_login_at", schema="app")
    op.drop_column("app_user", "failed_login_count", schema="app")
    op.drop_column("app_user", "password_changed_at", schema="app")
    op.drop_column("app_user", "email_verified_at", schema="app")
    op.drop_column("app_user", "account_state", schema="app")

