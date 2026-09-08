"""Replace the single watchlist with groups, preserving every historical ID."""

from alembic import op
import sqlalchemy as sa

revision = "20260907_000170"
down_revision = "20260903_000169"
branch_labels = None
depends_on = None

# Migration contracts are frozen here; never import mutable application policy.
MAX_API_ID = 9007199254740991


def _assert_empty(query: str, message: str) -> None:
    if op.get_bind().execute(sa.text(query)).first() is not None:
        raise RuntimeError("Watchlist migration reconciliation failed: " + message)


def _check_defaults() -> None:
    _assert_empty(
        """
        SELECT u.id FROM app.app_user u
        LEFT JOIN app.wealth_watchlist_group g ON g.user_id=u.id AND g.is_default
        GROUP BY u.id HAVING count(g.id) <> 1
    """,
        "each user must have exactly one default group",
    )
    _assert_empty(
        "SELECT id FROM app.wealth_watchlist_group WHERE NOT is_default",
        "unexpected custom groups",
    )


def _reconcile() -> None:
    old = "SELECT user_id, id, ts_code, created_at, updated_at FROM app.wealth_watchlist_item"
    new = """SELECT g.user_id, m.id, m.ts_code, m.created_at, m.updated_at
        FROM app.wealth_watchlist_membership m JOIN app.wealth_watchlist_group g ON g.id=m.group_id
        WHERE g.is_default"""
    for left, right in ((old, new), (new, old)):
        _assert_empty(f"({left}) EXCEPT ALL ({right})", "member values differ")
    _assert_empty(
        f"SELECT 1 WHERE (SELECT count(*) FROM ({old}) o) <> (SELECT count(*) FROM ({new}) n)",
        "member counts differ",
    )
    _assert_empty(
        """SELECT 1 WHERE
        (SELECT max(id) FROM app.wealth_watchlist_item) IS DISTINCT FROM
        (SELECT max(id) FROM app.wealth_watchlist_membership)
    """,
        "maximum ID differs",
    )
    # Row-number comparison proves complete order without loading all users into Python.
    old_order = f"SELECT user_id,id,ts_code,row_number() OVER (PARTITION BY user_id ORDER BY id) AS ordinal FROM ({old}) o"
    new_order = f"SELECT user_id,id,ts_code,row_number() OVER (PARTITION BY user_id ORDER BY id) AS ordinal FROM ({new}) n"
    for left, right in ((old_order, new_order), (new_order, old_order)):
        _assert_empty(
            f"({left}) EXCEPT ALL ({right})", "per-user ordered sequence differs"
        )
    for table in ("wealth_watchlist_group", "wealth_watchlist_membership"):
        _assert_empty(
            f"SELECT id FROM app.{table} WHERE id < 1 OR id > {MAX_API_ID}",
            "ID exceeds API range",
        )
    _assert_empty(
        "SELECT id FROM app.wealth_watchlist_membership WHERE is_pinned",
        "unexpected pin state",
    )


def _sequence(table: str) -> None:
    # table is an internal frozen identifier, never user input.
    op.execute(
        sa.text(f"""SELECT setval(pg_get_serial_sequence('app.{table}', 'id'),
        COALESCE((SELECT max(id) FROM app.{table}), 1),
        EXISTS(SELECT 1 FROM app.{table}))""")
    )
    sequence = op.get_bind().scalar(
        sa.text(f"SELECT pg_get_serial_sequence('app.{table}', 'id')")
    )
    last, called = (
        op.get_bind()
        .execute(sa.text(f"SELECT last_value, is_called FROM {sequence}"))
        .one()
    )
    maximum = op.get_bind().scalar(sa.text(f"SELECT max(id) FROM app.{table}"))
    if (last + 1 if called else last) <= (maximum or 0):
        raise RuntimeError("Watchlist migration sequence did not advance")


def _timestamps():
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def upgrade() -> None:
    op.create_table(
        "wealth_watchlist_group",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("color", sa.String(7), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["app.app_user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "name", name="uq_wealth_watchlist_group_user_name"
        ),
        sa.CheckConstraint(
            "length(name)>0", name=op.f("ck_wealth_watchlist_group_name_nonempty")
        ),
        sa.CheckConstraint(
            """(is_default AND name='我的自选' AND color IS NULL) OR
            (NOT is_default AND name<>'我的自选' AND color IS NOT NULL AND color IN
            ('#F7C76B','#5AA7FF','#A78BFA','#2DD4BF','#FB923C','#F472B6','#A3E635','#22D3EE'))""",
            name=op.f("ck_wealth_watchlist_group_identity"),
        ),
        schema="app",
    )
    op.create_index(
        "uq_wealth_watchlist_group_user_default",
        "wealth_watchlist_group",
        ["user_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("is_default"),
    )
    op.create_index(
        "idx_wealth_watchlist_group_user_id_id",
        "wealth_watchlist_group",
        ["user_id", "id"],
        schema="app",
    )
    op.execute("""INSERT INTO app.wealth_watchlist_group(user_id,name,is_default,color)
        SELECT id,'我的自选',true,NULL FROM app.app_user ORDER BY id""")
    _check_defaults()
    op.create_table(
        "wealth_watchlist_membership",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("ts_code", sa.String(16), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["group_id"], ["app.wealth_watchlist_group.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "group_id", "ts_code", name="uq_wealth_watchlist_membership_group_stock"
        ),
        schema="app",
    )
    op.create_index(
        "idx_wealth_watchlist_membership_group_pin_id",
        "wealth_watchlist_membership",
        ["group_id", "is_pinned", "id"],
        schema="app",
    )
    op.create_index(
        "idx_wealth_watchlist_membership_stock_group",
        "wealth_watchlist_membership",
        ["ts_code", "group_id"],
        schema="app",
    )
    op.execute("""INSERT INTO app.wealth_watchlist_membership(id,group_id,ts_code,is_pinned,created_at,updated_at)
        SELECT w.id,g.id,w.ts_code,false,w.created_at,w.updated_at FROM app.wealth_watchlist_item w
        JOIN app.wealth_watchlist_group g ON g.user_id=w.user_id AND g.is_default ORDER BY w.id""")
    _sequence("wealth_watchlist_membership")
    _reconcile()
    op.drop_table("wealth_watchlist_item", schema="app")


def downgrade() -> None:
    _check_defaults()
    _assert_empty(
        """SELECT m.id FROM app.wealth_watchlist_membership m
        LEFT JOIN app.wealth_watchlist_group g ON g.id=m.group_id
        WHERE m.is_pinned OR g.id IS NULL OR NOT g.is_default""",
        "v2 data cannot be downgraded losslessly",
    )
    op.create_table(
        "wealth_watchlist_item",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ts_code", sa.String(16), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["app.app_user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "ts_code", name="uq_wealth_watchlist_item_user_stock"
        ),
        schema="app",
    )
    op.create_index(
        "idx_wealth_watchlist_item_user_id_id",
        "wealth_watchlist_item",
        ["user_id", "id"],
        schema="app",
    )
    op.execute("""INSERT INTO app.wealth_watchlist_item(id,user_id,ts_code,created_at,updated_at)
        SELECT m.id,g.user_id,m.ts_code,m.created_at,m.updated_at FROM app.wealth_watchlist_membership m
        JOIN app.wealth_watchlist_group g ON g.id=m.group_id ORDER BY m.id""")
    _reconcile()
    _sequence("wealth_watchlist_item")
    op.drop_table("wealth_watchlist_membership", schema="app")
    op.drop_table("wealth_watchlist_group", schema="app")
