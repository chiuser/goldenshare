"""add raw_biying moneyflow table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000049"
down_revision = "20260416_000048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_biying")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("moneyflow", schema="raw_biying"):
        return
    op.create_table(
        "moneyflow",
        sa.Column("dm", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("mc", sa.String(length=64)),
        sa.Column("quote_time", sa.DateTime(timezone=False)),
        sa.Column("zmbzds", sa.BigInteger()),
        sa.Column("zmszds", sa.BigInteger()),
        sa.Column("dddx", sa.Numeric(18, 4)),
        sa.Column("zddy", sa.Numeric(18, 4)),
        sa.Column("ddcf", sa.Numeric(18, 4)),
        sa.Column("zmbzdszl", sa.BigInteger()),
        sa.Column("zmszdszl", sa.BigInteger()),
        sa.Column("cjbszl", sa.BigInteger()),
        sa.Column("zmbtdcje", sa.Numeric(30, 4)),
        sa.Column("zmbddcje", sa.Numeric(30, 4)),
        sa.Column("zmbzdcje", sa.Numeric(30, 4)),
        sa.Column("zmbxdcje", sa.Numeric(30, 4)),
        sa.Column("zmstdcje", sa.Numeric(30, 4)),
        sa.Column("zmsddcje", sa.Numeric(30, 4)),
        sa.Column("zmszdcje", sa.Numeric(30, 4)),
        sa.Column("zmsxdcje", sa.Numeric(30, 4)),
        sa.Column("bdmbtdcje", sa.Numeric(30, 4)),
        sa.Column("bdmbddcje", sa.Numeric(30, 4)),
        sa.Column("bdmbzdcje", sa.Numeric(30, 4)),
        sa.Column("bdmbxdcje", sa.Numeric(30, 4)),
        sa.Column("bdmstdcje", sa.Numeric(30, 4)),
        sa.Column("bdmsddcje", sa.Numeric(30, 4)),
        sa.Column("bdmszdcje", sa.Numeric(30, 4)),
        sa.Column("bdmsxdcje", sa.Numeric(30, 4)),
        sa.Column("zmbtdcjl", sa.BigInteger()),
        sa.Column("zmbddcjl", sa.BigInteger()),
        sa.Column("zmbzdcjl", sa.BigInteger()),
        sa.Column("zmbxdcjl", sa.BigInteger()),
        sa.Column("zmstdcjl", sa.BigInteger()),
        sa.Column("zmsddcjl", sa.BigInteger()),
        sa.Column("zmszdcjl", sa.BigInteger()),
        sa.Column("zmsxdcjl", sa.BigInteger()),
        sa.Column("bdmbtdcjl", sa.BigInteger()),
        sa.Column("bdmbddcjl", sa.BigInteger()),
        sa.Column("bdmbzdcjl", sa.BigInteger()),
        sa.Column("bdmbxdcjl", sa.BigInteger()),
        sa.Column("bdmstdcjl", sa.BigInteger()),
        sa.Column("bdmsddcjl", sa.BigInteger()),
        sa.Column("bdmszdcjl", sa.BigInteger()),
        sa.Column("bdmsxdcjl", sa.BigInteger()),
        sa.Column("zmbtdcjzl", sa.Numeric(30, 4)),
        sa.Column("zmbddcjzl", sa.Numeric(30, 4)),
        sa.Column("zmbzdcjzl", sa.Numeric(30, 4)),
        sa.Column("zmbxdcjzl", sa.Numeric(30, 4)),
        sa.Column("zmstdcjzl", sa.Numeric(30, 4)),
        sa.Column("zmsddcjzl", sa.Numeric(30, 4)),
        sa.Column("zmszdcjzl", sa.Numeric(30, 4)),
        sa.Column("zmsxdcjzl", sa.Numeric(30, 4)),
        sa.Column("bdmbtdcjzl", sa.Numeric(30, 4)),
        sa.Column("bdmbddcjzl", sa.Numeric(30, 4)),
        sa.Column("bdmbzdcjzl", sa.Numeric(30, 4)),
        sa.Column("bdmbxdcjzl", sa.Numeric(30, 4)),
        sa.Column("bdmstdcjzl", sa.Numeric(30, 4)),
        sa.Column("bdmsddcjzl", sa.Numeric(30, 4)),
        sa.Column("bdmszdcjzl", sa.Numeric(30, 4)),
        sa.Column("bdmsxdcjzl", sa.Numeric(30, 4)),
        sa.Column("zmbtdcjzlv", sa.BigInteger()),
        sa.Column("zmbddcjzlv", sa.BigInteger()),
        sa.Column("zmbzdcjzlv", sa.BigInteger()),
        sa.Column("zmbxdcjzlv", sa.BigInteger()),
        sa.Column("zmstdcjzlv", sa.BigInteger()),
        sa.Column("zmsddcjzlv", sa.BigInteger()),
        sa.Column("zmszdcjzlv", sa.BigInteger()),
        sa.Column("zmsxdcjzlv", sa.BigInteger()),
        sa.Column("bdmbtdcjzlv", sa.BigInteger()),
        sa.Column("bdmbddcjzlv", sa.BigInteger()),
        sa.Column("bdmbzdcjzlv", sa.BigInteger()),
        sa.Column("bdmbxdcjzlv", sa.BigInteger()),
        sa.Column("bdmstdcjzlv", sa.BigInteger()),
        sa.Column("bdmsddcjzlv", sa.BigInteger()),
        sa.Column("bdmszdcjzlv", sa.BigInteger()),
        sa.Column("bdmsxdcjzlv", sa.BigInteger()),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'hsstock_history_transaction'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw_biying",
    )
    op.create_index(
        "idx_raw_biying_moneyflow_trade_date",
        "moneyflow",
        ["trade_date"],
        schema="raw_biying",
    )
    op.create_index(
        "idx_raw_biying_moneyflow_dm_trade_date",
        "moneyflow",
        ["dm", "trade_date"],
        schema="raw_biying",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("moneyflow", schema="raw_biying"):
        return
    op.drop_index("idx_raw_biying_moneyflow_dm_trade_date", table_name="moneyflow", schema="raw_biying")
    op.drop_index("idx_raw_biying_moneyflow_trade_date", table_name="moneyflow", schema="raw_biying")
    op.drop_table("moneyflow", schema="raw_biying")
