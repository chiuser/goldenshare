from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core_multi.security_std import SecurityStd


DiffType = Literal["only_tushare", "only_biying", "comparable_diff"]


@dataclass(frozen=True)
class StockBasicDiffSample:
    ts_code: str
    diff_type: DiffType
    tushare_name: str | None
    biying_name: str | None
    tushare_exchange: str | None
    biying_exchange: str | None
    tushare_name_norm: str
    biying_name_norm: str
    tushare_exchange_norm: str
    biying_exchange_norm: str


@dataclass(frozen=True)
class StockBasicReconcileReport:
    total_union: int
    comparable: int
    only_tushare: int
    only_biying: int
    comparable_diff: int
    samples: dict[DiffType, list[StockBasicDiffSample]]


class StockBasicReconcileService:
    _WS_PATTERN = re.compile(r"\s+")
    _EXCHANGE_MAP = {
        "SZSE": "SZ",
        "SSE": "SH",
        "BSE": "BJ",
    }

    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        return cls._WS_PATTERN.sub("", (value or "").strip())

    @classmethod
    def normalize_exchange(cls, value: str | None) -> str:
        raw = (value or "").strip().upper()
        if not raw:
            return ""
        return cls._EXCHANGE_MAP.get(raw, raw)

    def run(self, session: Session, *, sample_limit: int = 20) -> StockBasicReconcileReport:
        rows = list(
            session.scalars(
                select(SecurityStd).where(SecurityStd.source_key.in_(["tushare", "biying"]))
            )
        )
        tushare_by_code: dict[str, SecurityStd] = {}
        biying_by_code: dict[str, SecurityStd] = {}
        for row in rows:
            if row.source_key == "tushare":
                tushare_by_code[row.ts_code] = row
            elif row.source_key == "biying":
                biying_by_code[row.ts_code] = row

        all_codes = sorted(set(tushare_by_code) | set(biying_by_code))
        only_tushare = 0
        only_biying = 0
        comparable = 0
        comparable_diff = 0
        samples: dict[DiffType, list[StockBasicDiffSample]] = {
            "only_tushare": [],
            "only_biying": [],
            "comparable_diff": [],
        }

        for ts_code in all_codes:
            t = tushare_by_code.get(ts_code)
            b = biying_by_code.get(ts_code)

            if t is None:
                only_biying += 1
                if len(samples["only_biying"]) < sample_limit:
                    samples["only_biying"].append(
                        StockBasicDiffSample(
                            ts_code=ts_code,
                            diff_type="only_biying",
                            tushare_name=None,
                            biying_name=b.name if b else None,
                            tushare_exchange=None,
                            biying_exchange=b.exchange if b else None,
                            tushare_name_norm="",
                            biying_name_norm=self.normalize_name(b.name if b else None),
                            tushare_exchange_norm="",
                            biying_exchange_norm=self.normalize_exchange(b.exchange if b else None),
                        )
                    )
                continue

            if b is None:
                only_tushare += 1
                if len(samples["only_tushare"]) < sample_limit:
                    samples["only_tushare"].append(
                        StockBasicDiffSample(
                            ts_code=ts_code,
                            diff_type="only_tushare",
                            tushare_name=t.name,
                            biying_name=None,
                            tushare_exchange=t.exchange,
                            biying_exchange=None,
                            tushare_name_norm=self.normalize_name(t.name),
                            biying_name_norm="",
                            tushare_exchange_norm=self.normalize_exchange(t.exchange),
                            biying_exchange_norm="",
                        )
                    )
                continue

            comparable += 1
            t_name_norm = self.normalize_name(t.name)
            b_name_norm = self.normalize_name(b.name)
            t_exchange_norm = self.normalize_exchange(t.exchange)
            b_exchange_norm = self.normalize_exchange(b.exchange)
            if t_name_norm != b_name_norm or t_exchange_norm != b_exchange_norm:
                comparable_diff += 1
                if len(samples["comparable_diff"]) < sample_limit:
                    samples["comparable_diff"].append(
                        StockBasicDiffSample(
                            ts_code=ts_code,
                            diff_type="comparable_diff",
                            tushare_name=t.name,
                            biying_name=b.name,
                            tushare_exchange=t.exchange,
                            biying_exchange=b.exchange,
                            tushare_name_norm=t_name_norm,
                            biying_name_norm=b_name_norm,
                            tushare_exchange_norm=t_exchange_norm,
                            biying_exchange_norm=b_exchange_norm,
                        )
                    )

        return StockBasicReconcileReport(
            total_union=len(all_codes),
            comparable=comparable,
            only_tushare=only_tushare,
            only_biying=only_biying,
            comparable_diff=comparable_diff,
            samples=samples,
        )
