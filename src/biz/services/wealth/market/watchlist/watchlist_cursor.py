from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import re

from src.biz.services.wealth.market.watchlist.watchlist_policy import (
    MAX_API_ID,
    SORT_FIELDS,
    WatchlistError,
)


@dataclass(frozen=True, slots=True)
class WatchlistCursor:
    group_id: int
    sort_by: str | None
    direction: str | None
    observed: date | None
    pin_rank: int
    missing_rank: int
    value: Decimal | None
    membership_id: int

    def encode(self) -> str:
        payload = dict(
            v=1,
            g=self.group_id,
            s=self.sort_by,
            d=self.direction,
            o=self.observed.isoformat() if self.observed else None,
            p=self.pin_rank,
            m=self.missing_rank,
            x=str(self.value) if self.value is not None else None,
            i=self.membership_id,
        )
        token = (
            base64.urlsafe_b64encode(
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
            )
            .decode()
            .rstrip("=")
        )
        # Enforce the same contract on produced tokens, not only incoming tokens.
        self.decode(
            token,
            group_id=self.group_id,
            sort_by=self.sort_by,
            direction=self.direction,
            observed=self.observed,
        )
        return token

    @classmethod
    def decode(
        cls,
        token: str,
        *,
        group_id: int,
        sort_by: str | None,
        direction: str | None,
        observed: date | None,
    ) -> WatchlistCursor:
        def exact_object(pairs):
            result = dict(pairs)
            if len(result) != len(pairs):
                raise ValueError("duplicate keys")
            return result

        try:
            if (
                not 1 <= len(token) <= 1024
                or re.fullmatch(r"[A-Za-z0-9_-]+", token) is None
            ):
                raise ValueError("invalid token")
            raw = base64.b64decode(
                token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
            )
            if base64.urlsafe_b64encode(raw).decode().rstrip("=") != token:
                raise ValueError("invalid encoding")
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=exact_object)
            if type(data) is not dict or set(data) != set("vgsdopmxi"):
                raise ValueError("invalid keys")
            if type(data["v"]) is not int or data["v"] != 1:
                raise ValueError("version")
            for key in ("g", "i"):
                if type(data[key]) is not int or not 1 <= data[key] <= MAX_API_ID:
                    raise ValueError("id")
            for key in ("p", "m"):
                if type(data[key]) is not int or data[key] not in (0, 1):
                    raise ValueError("rank")
            if data["s"] is None:
                if data["d"] is not None or data["m"] != 0 or data["x"] is not None:
                    raise ValueError("default sort")
            elif data["s"] not in SORT_FIELDS or data["d"] not in ("asc", "desc"):
                raise ValueError("sort")
            day = None
            if data["o"] is not None:
                if (
                    type(data["o"]) is not str
                    or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", data["o"]) is None
                ):
                    raise ValueError("date")
                day = date.fromisoformat(data["o"])
            value = None
            if data["s"] is not None and data["m"] == 0:
                if (
                    type(data["x"]) is not str
                    or re.fullmatch(
                        r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?",
                        data["x"],
                    )
                    is None
                ):
                    raise ValueError("decimal")
                value = Decimal(data["x"])
                if not value.is_finite():
                    raise ValueError("nonfinite")
            elif data["x"] is not None:
                raise ValueError("missing decimal")
            if (data["g"], data["s"], data["d"], day) != (
                group_id,
                sort_by,
                direction,
                observed,
            ):
                raise ValueError("context")
            return cls(
                group_id,
                sort_by,
                direction,
                day,
                data["p"],
                data["m"],
                value,
                data["i"],
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            InvalidOperation,
            OverflowError,
            RecursionError,
        ) as exc:
            raise WatchlistError(
                "WL_CURSOR_INVALID", "分页游标无效，请重新加载"
            ) from exc
