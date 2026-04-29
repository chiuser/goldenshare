from __future__ import annotations

ACCOUNT_STATE_PENDING_VERIFICATION = "pending_verification"
ACCOUNT_STATE_ACTIVE = "active"
ACCOUNT_STATE_SUSPENDED = "suspended"
ACCOUNT_STATE_LOCKED = "locked"

AUTH_ACTION_VERIFY_EMAIL = "verify_email"
AUTH_ACTION_RESET_PASSWORD = "reset_password"

ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_ANALYST = "analyst"
ROLE_VIEWER = "viewer"

DEFAULT_ROLES: tuple[tuple[str, str, str], ...] = (
    (ROLE_ADMIN, "管理员", "平台管理员"),
    (ROLE_OPERATOR, "操作员", "运维操作角色"),
    (ROLE_ANALYST, "分析员", "只读分析角色"),
    (ROLE_VIEWER, "访客", "基础查看角色"),
)

DEFAULT_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("ops.read", "运维查看", "查看运维数据"),
    ("ops.write", "运维配置", "修改运维配置"),
    ("ops.execute", "运维执行", "执行运维动作"),
    ("quote.read", "行情查看", "读取行情数据"),
    ("user.manage", "用户管理", "管理用户和角色"),
    ("auth.audit.read", "认证审计查看", "查看认证审计日志"),
)

DEFAULT_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    ROLE_ADMIN: ("ops.read", "ops.write", "ops.execute", "quote.read", "user.manage", "auth.audit.read"),
    ROLE_OPERATOR: ("ops.read", "ops.write", "ops.execute"),
    ROLE_ANALYST: ("quote.read",),
    ROLE_VIEWER: ("quote.read",),
}
