from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
from typing import Any, Literal


XxmPeriod = Literal["day", "m60", "m90", "m120"]


@dataclass(frozen=True, slots=True)
class XxmBar:
    time: str
    close: float
    dif: float
    dea: float
    hist: float
    completed: bool = True

    def validate(self, period: XxmPeriod) -> None:
        if not self.completed or self.close <= 0 or not all(
            math.isfinite(v) for v in (self.close, self.dif, self.dea, self.hist)
        ):
            raise ValueError("XXM requires finite completed bars and positive closes")
        if period == "day":
            if date.fromisoformat(self.time).isoformat() != self.time:
                raise ValueError("Invalid daily time")
        else:
            stamp = datetime.fromisoformat(self.time)
            if stamp.utcoffset() != timedelta(hours=8):
                raise ValueError("Minute endpoint must include +08:00")


@dataclass(slots=True)
class Wave:
    sign: int
    start: str
    end: str
    count: int
    price: float
    dif: float
    price_at: str
    dif_at: str

    def reference(self) -> dict[str, Any]:
        return {"startTime": self.start, "endTime": self.end, "price": self.price, "dif": self.dif}


@dataclass(frozen=True, slots=True)
class XxmStep:
    point: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    histories: tuple[dict[str, Any], ...]
