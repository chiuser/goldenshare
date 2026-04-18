from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.models.raw.raw_moneyflow import RawMoneyflow
from src.foundation.models.raw_multi.raw_biying_moneyflow import RawBiyingMoneyflow


DiffType = Literal["only_tushare", "only_biying", "comparable_diff"]
FieldKey = Literal[
    "buy_sm_amount",
    "buy_md_amount",
    "buy_lg_amount",
    "buy_elg_amount",
    "sell_sm_amount",
    "sell_md_amount",
    "sell_lg_amount",
    "sell_elg_amount",
    "net_mf_amount",
]


@dataclass(frozen=True)
class MoneyflowDiffSample:
    ts_code: str
    trade_date: date
    diff_type: DiffType
    field: FieldKey | None
    tushare_value: Decimal | None
    biying_value: Decimal | None
    abs_diff: Decimal | None
    rel_diff: Decimal | None
    note: str | None


@dataclass(frozen=True)
class MoneyflowReconcileReport:
    start_date: date
    end_date: date
    total_union: int
    comparable: int
    only_tushare: int
    only_biying: int
    comparable_diff: int
    direction_mismatch: int
    samples: dict[DiffType, list[MoneyflowDiffSample]]


@dataclass(frozen=True)
class _BiyingComparableRow:
    buy_sm_amount: Decimal | None
    buy_md_amount: Decimal | None
    buy_lg_amount: Decimal | None
    buy_elg_amount: Decimal | None
    sell_sm_amount: Decimal | None
    sell_md_amount: Decimal | None
    sell_lg_amount: Decimal | None
    sell_elg_amount: Decimal | None
    net_mf_amount: Decimal | None


@dataclass(frozen=True)
class _FieldViolation:
    field: FieldKey
    tushare_value: Decimal | None
    biying_value: Decimal | None
    abs_diff: Decimal | None
    rel_diff: Decimal | None
    note: str | None


class MoneyflowReconcileService:
    _COMPARE_FIELDS: tuple[FieldKey, ...] = (
        "buy_sm_amount",
        "buy_md_amount",
        "buy_lg_amount",
        "buy_elg_amount",
        "sell_sm_amount",
        "sell_md_amount",
        "sell_lg_amount",
        "sell_elg_amount",
        "net_mf_amount",
    )
    _ZERO = Decimal("0")

    def run(
        self,
        session: Session,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        range_days: int = 5,
        sample_limit: int = 20,
        abs_tol: Decimal = Decimal("1"),
        rel_tol: Decimal = Decimal("0.03"),
    ) -> MoneyflowReconcileReport:
        resolved_start, resolved_end = self._resolve_date_range(
            session,
            start_date=start_date,
            end_date=end_date,
            range_days=max(1, range_days),
        )
        if resolved_start > resolved_end:
            raise ValueError("start_date must be <= end_date")

        tushare_rows = list(
            session.scalars(
                select(RawMoneyflow).where(
                    RawMoneyflow.trade_date >= resolved_start,
                    RawMoneyflow.trade_date <= resolved_end,
                )
            )
        )
        biying_rows = list(
            session.scalars(
                select(RawBiyingMoneyflow).where(
                    RawBiyingMoneyflow.trade_date >= resolved_start,
                    RawBiyingMoneyflow.trade_date <= resolved_end,
                )
            )
        )

        tushare_by_key: dict[tuple[str, date], RawMoneyflow] = {}
        for row in tushare_rows:
            key = (self._normalize_ts_code(row.ts_code), row.trade_date)
            tushare_by_key[key] = row

        biying_by_key: dict[tuple[str, date], _BiyingComparableRow] = {}
        for row in biying_rows:
            ts_code = self._normalize_dm_to_ts_code(row.dm)
            if not ts_code:
                continue
            key = (ts_code, row.trade_date)
            biying_by_key[key] = self._build_biying_row(row)

        all_keys = sorted(set(tushare_by_key.keys()) | set(biying_by_key.keys()))

        only_tushare = 0
        only_biying = 0
        comparable = 0
        comparable_diff = 0
        direction_mismatch = 0

        samples: dict[DiffType, list[MoneyflowDiffSample]] = {
            "only_tushare": [],
            "only_biying": [],
            "comparable_diff": [],
        }

        for key in all_keys:
            ts_code, trade_date = key
            t_row = tushare_by_key.get(key)
            b_row = biying_by_key.get(key)

            if t_row is None:
                only_biying += 1
                if len(samples["only_biying"]) < sample_limit:
                    samples["only_biying"].append(
                        MoneyflowDiffSample(
                            ts_code=ts_code,
                            trade_date=trade_date,
                            diff_type="only_biying",
                            field=None,
                            tushare_value=None,
                            biying_value=None,
                            abs_diff=None,
                            rel_diff=None,
                            note="仅 BIYING 存在",
                        )
                    )
                continue

            if b_row is None:
                only_tushare += 1
                if len(samples["only_tushare"]) < sample_limit:
                    samples["only_tushare"].append(
                        MoneyflowDiffSample(
                            ts_code=ts_code,
                            trade_date=trade_date,
                            diff_type="only_tushare",
                            field=None,
                            tushare_value=None,
                            biying_value=None,
                            abs_diff=None,
                            rel_diff=None,
                            note="仅 Tushare 存在",
                        )
                    )
                continue

            comparable += 1
            violations = self._find_violations(t_row=t_row, b_row=b_row, abs_tol=abs_tol, rel_tol=rel_tol)
            if not violations:
                continue
            comparable_diff += 1
            if any(item.note == "净流入方向不一致" for item in violations):
                direction_mismatch += 1
            if len(samples["comparable_diff"]) < sample_limit:
                top = max(
                    violations,
                    key=lambda item: (
                        item.abs_diff if item.abs_diff is not None else Decimal("0"),
                        item.rel_diff if item.rel_diff is not None else Decimal("0"),
                    ),
                )
                samples["comparable_diff"].append(
                    MoneyflowDiffSample(
                        ts_code=ts_code,
                        trade_date=trade_date,
                        diff_type="comparable_diff",
                        field=top.field,
                        tushare_value=top.tushare_value,
                        biying_value=top.biying_value,
                        abs_diff=top.abs_diff,
                        rel_diff=top.rel_diff,
                        note=top.note,
                    )
                )

        return MoneyflowReconcileReport(
            start_date=resolved_start,
            end_date=resolved_end,
            total_union=len(all_keys),
            comparable=comparable,
            only_tushare=only_tushare,
            only_biying=only_biying,
            comparable_diff=comparable_diff,
            direction_mismatch=direction_mismatch,
            samples=samples,
        )

    def _resolve_date_range(
        self,
        session: Session,
        *,
        start_date: date | None,
        end_date: date | None,
        range_days: int,
    ) -> tuple[date, date]:
        if end_date is None:
            tushare_max = session.scalar(select(func.max(RawMoneyflow.trade_date)))
            biying_max = session.scalar(select(func.max(RawBiyingMoneyflow.trade_date)))
            latest = max(tushare_max or date.min, biying_max or date.min)
            end_date = latest if latest != date.min else date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=range_days - 1)
        return start_date, end_date

    def _find_violations(
        self,
        *,
        t_row: RawMoneyflow,
        b_row: _BiyingComparableRow,
        abs_tol: Decimal,
        rel_tol: Decimal,
    ) -> list[_FieldViolation]:
        violations: list[_FieldViolation] = []
        for field in self._COMPARE_FIELDS:
            t_value = self._to_decimal(getattr(t_row, field))
            b_value = self._to_decimal(getattr(b_row, field))
            violation = self._compare_field(
                field=field,
                t_value=t_value,
                b_value=b_value,
                abs_tol=abs_tol,
                rel_tol=rel_tol,
            )
            if violation is not None:
                violations.append(violation)
        if self._is_direction_mismatch(t_row.net_mf_amount, b_row.net_mf_amount):
            violations.append(
                _FieldViolation(
                    field="net_mf_amount",
                    tushare_value=self._to_decimal(t_row.net_mf_amount),
                    biying_value=self._to_decimal(b_row.net_mf_amount),
                    abs_diff=None,
                    rel_diff=None,
                    note="净流入方向不一致",
                )
            )
        return violations

    def _build_biying_row(self, row: RawBiyingMoneyflow) -> _BiyingComparableRow:
        buy_sm = self._to_decimal(row.zmbxdcje)
        buy_md = self._to_decimal(row.zmbzdcje)
        buy_lg = self._to_decimal(row.zmbddcje)
        buy_elg = self._to_decimal(row.zmbtdcje)
        sell_sm = self._to_decimal(row.zmsxdcje)
        sell_md = self._to_decimal(row.zmszdcje)
        sell_lg = self._to_decimal(row.zmsddcje)
        sell_elg = self._to_decimal(row.zmstdcje)
        buy_total = self._sum_decimals((buy_sm, buy_md, buy_lg, buy_elg))
        sell_total = self._sum_decimals((sell_sm, sell_md, sell_lg, sell_elg))
        net = None
        if buy_total is not None or sell_total is not None:
            net = (buy_total or self._ZERO) - (sell_total or self._ZERO)
        return _BiyingComparableRow(
            buy_sm_amount=buy_sm,
            buy_md_amount=buy_md,
            buy_lg_amount=buy_lg,
            buy_elg_amount=buy_elg,
            sell_sm_amount=sell_sm,
            sell_md_amount=sell_md,
            sell_lg_amount=sell_lg,
            sell_elg_amount=sell_elg,
            net_mf_amount=net,
        )

    def _compare_field(
        self,
        *,
        field: FieldKey,
        t_value: Decimal | None,
        b_value: Decimal | None,
        abs_tol: Decimal,
        rel_tol: Decimal,
    ) -> _FieldViolation | None:
        if t_value is None and b_value is None:
            return None
        if t_value is None or b_value is None:
            return _FieldViolation(
                field=field,
                tushare_value=t_value,
                biying_value=b_value,
                abs_diff=None,
                rel_diff=None,
                note="字段缺失不一致",
            )

        abs_diff = abs(t_value - b_value)
        base = max(abs(t_value), abs(b_value), Decimal("1"))
        rel_diff = abs_diff / base
        if abs_diff > abs_tol and rel_diff > rel_tol:
            return _FieldViolation(
                field=field,
                tushare_value=t_value,
                biying_value=b_value,
                abs_diff=abs_diff,
                rel_diff=rel_diff,
                note=None,
            )
        return None

    @staticmethod
    def _sum_decimals(values: tuple[Decimal | None, ...]) -> Decimal | None:
        total = Decimal("0")
        seen = False
        for value in values:
            if value is not None:
                total += value
                seen = True
        if not seen:
            return None
        return total

    @staticmethod
    def _to_decimal(value) -> Decimal | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return Decimal(str(value))

    @staticmethod
    def _normalize_ts_code(value: str | None) -> str:
        return (value or "").strip().upper()

    @classmethod
    def _normalize_dm_to_ts_code(cls, dm: str | None) -> str:
        raw = (dm or "").strip().upper()
        if not raw:
            return ""
        if "." in raw:
            return raw
        if len(raw) == 6 and raw.isdigit():
            if raw.startswith("6"):
                return f"{raw}.SH"
            if raw.startswith(("4", "8")):
                return f"{raw}.BJ"
            return f"{raw}.SZ"
        return raw

    @staticmethod
    def _sign(value: Decimal | None) -> int:
        if value is None:
            return 0
        if value > 0:
            return 1
        if value < 0:
            return -1
        return 0

    def _is_direction_mismatch(self, left, right) -> bool:  # type: ignore[no-untyped-def]
        return self._sign(self._to_decimal(left)) != self._sign(self._to_decimal(right))
