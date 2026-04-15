from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawBiyingMoneyflow(Base):
    __tablename__ = "moneyflow"
    __table_args__ = (
        Index("idx_raw_biying_moneyflow_trade_date", "trade_date"),
        Index("idx_raw_biying_moneyflow_dm_trade_date", "dm", "trade_date"),
        {"schema": "raw_biying"},
    )

    dm: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    mc: Mapped[str | None] = mapped_column(String(64))
    quote_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    zmbzds: Mapped[int | None] = mapped_column(BigInteger)
    zmszds: Mapped[int | None] = mapped_column(BigInteger)
    dddx: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    zddy: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    ddcf: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    zmbzdszl: Mapped[int | None] = mapped_column(BigInteger)
    zmszdszl: Mapped[int | None] = mapped_column(BigInteger)
    cjbszl: Mapped[int | None] = mapped_column(BigInteger)

    zmbtdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmbddcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmbzdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmbxdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmstdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmsddcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmszdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmsxdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmbtdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmbddcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmbzdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmbxdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmstdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmsddcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmszdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmsxdcje: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))

    zmbtdcjl: Mapped[int | None] = mapped_column(BigInteger)
    zmbddcjl: Mapped[int | None] = mapped_column(BigInteger)
    zmbzdcjl: Mapped[int | None] = mapped_column(BigInteger)
    zmbxdcjl: Mapped[int | None] = mapped_column(BigInteger)
    zmstdcjl: Mapped[int | None] = mapped_column(BigInteger)
    zmsddcjl: Mapped[int | None] = mapped_column(BigInteger)
    zmszdcjl: Mapped[int | None] = mapped_column(BigInteger)
    zmsxdcjl: Mapped[int | None] = mapped_column(BigInteger)
    bdmbtdcjl: Mapped[int | None] = mapped_column(BigInteger)
    bdmbddcjl: Mapped[int | None] = mapped_column(BigInteger)
    bdmbzdcjl: Mapped[int | None] = mapped_column(BigInteger)
    bdmbxdcjl: Mapped[int | None] = mapped_column(BigInteger)
    bdmstdcjl: Mapped[int | None] = mapped_column(BigInteger)
    bdmsddcjl: Mapped[int | None] = mapped_column(BigInteger)
    bdmszdcjl: Mapped[int | None] = mapped_column(BigInteger)
    bdmsxdcjl: Mapped[int | None] = mapped_column(BigInteger)

    zmbtdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmbddcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmbzdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmbxdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmstdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmsddcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmszdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    zmsxdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmbtdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmbddcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmbzdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmbxdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmstdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmsddcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmszdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    bdmsxdcjzl: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))

    zmbtdcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    zmbddcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    zmbzdcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    zmbxdcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    zmstdcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    zmsddcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    zmszdcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    zmsxdcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    bdmbtdcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    bdmbddcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    bdmbzdcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    bdmbxdcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    bdmstdcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    bdmsddcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    bdmszdcjzlv: Mapped[int | None] = mapped_column(BigInteger)
    bdmsxdcjzlv: Mapped[int | None] = mapped_column(BigInteger)

    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'hsstock_history_transaction'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
