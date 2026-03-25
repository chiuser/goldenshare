from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from sqlalchemy import Numeric
from sqlalchemy.orm import mapped_column


Numeric18_4 = Annotated[Decimal | None, mapped_column(Numeric(18, 4))]
Numeric20_4 = Annotated[Decimal | None, mapped_column(Numeric(20, 4))]
Numeric20_8 = Annotated[Decimal | None, mapped_column(Numeric(20, 8))]
Numeric12_4 = Annotated[Decimal | None, mapped_column(Numeric(12, 4))]
Numeric12_6 = Annotated[Decimal | None, mapped_column(Numeric(12, 6))]
Numeric10_4 = Annotated[Decimal | None, mapped_column(Numeric(10, 4))]
