from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from math import floor
from statistics import mean
from typing import Any, Callable

from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session

from src.biz.services.market_mood_calculator import MarketMoodCalculator
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.equity_stk_limit import EquityStkLimit
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing


@dataclass(frozen=True)
class MoodWalkForwardPoint:
    trade_date: date
    fold_index: int
    mti: float
    msi: float
    rsk: float
    p_env_continue: float
    p_mainline_expand: float
    p_risk_event: float
    y_env_continue: int | None
    y_mainline_expand: int | None
    y_risk_event: int | None
    y_red_next: float | None
    y_tradable_up_next: float | None
    recommended_playbook: str
    recommended_exposure: float
    allow_chase: bool
    fallback_level: str


@dataclass(frozen=True)
class MoodWalkForwardFold:
    fold_index: int
    train_start: date
    train_end: date
    valid_start: date
    valid_end: date
    test_start: date
    test_end: date
    train_size: int
    valid_size: int
    test_size: int
    env_brier: float | None
    main_brier: float | None
    risk_brier: float | None
    mti_red_rank_ic: float | None
    msi_tradable_up_rank_ic: float | None


@dataclass(frozen=True)
class MoodWalkForwardReport:
    common_start_date: date
    common_end_date: date
    common_days: int
    signal_days: int
    folds: list[MoodWalkForwardFold]
    aggregate_metrics: dict[str, float | None]
    playbook_distribution: dict[str, int]
    points: list[MoodWalkForwardPoint]

    def to_json(self, *, include_points: bool = False) -> str:
        payload: dict[str, Any] = {
            "common_start_date": self.common_start_date.isoformat(),
            "common_end_date": self.common_end_date.isoformat(),
            "common_days": self.common_days,
            "signal_days": self.signal_days,
            "fold_count": len(self.folds),
            "folds": [
                {
                    "fold_index": fold.fold_index,
                    "train_start": fold.train_start.isoformat(),
                    "train_end": fold.train_end.isoformat(),
                    "valid_start": fold.valid_start.isoformat(),
                    "valid_end": fold.valid_end.isoformat(),
                    "test_start": fold.test_start.isoformat(),
                    "test_end": fold.test_end.isoformat(),
                    "train_size": fold.train_size,
                    "valid_size": fold.valid_size,
                    "test_size": fold.test_size,
                    "env_brier": fold.env_brier,
                    "main_brier": fold.main_brier,
                    "risk_brier": fold.risk_brier,
                    "mti_red_rank_ic": fold.mti_red_rank_ic,
                    "msi_tradable_up_rank_ic": fold.msi_tradable_up_rank_ic,
                }
                for fold in self.folds
            ],
            "aggregate_metrics": self.aggregate_metrics,
            "playbook_distribution": self.playbook_distribution,
        }
        if include_points:
            payload["points"] = [
                {
                    "trade_date": point.trade_date.isoformat(),
                    "fold_index": point.fold_index,
                    "mti": point.mti,
                    "msi": point.msi,
                    "rsk": point.rsk,
                    "p_env_continue": point.p_env_continue,
                    "p_mainline_expand": point.p_mainline_expand,
                    "p_risk_event": point.p_risk_event,
                    "y_env_continue": point.y_env_continue,
                    "y_mainline_expand": point.y_mainline_expand,
                    "y_risk_event": point.y_risk_event,
                    "y_red_next": point.y_red_next,
                    "y_tradable_up_next": point.y_tradable_up_next,
                    "recommended_playbook": point.recommended_playbook,
                    "recommended_exposure": point.recommended_exposure,
                    "allow_chase": point.allow_chase,
                    "fallback_level": point.fallback_level,
                }
                for point in self.points
            ]
        return json.dumps(payload, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class _ScoreRow:
    trade_date: date
    mti: float
    msi: float
    rsk: float
    delta_mti: float
    delta_msi: float
    delta_rsk: float
    red_rate: float | None
    tradable_up_rate: float | None
    mainline_concentration: float | None
    high_collapse_rate: float | None
    blast_rate: float | None
    limit_down_rate: float | None


@dataclass(frozen=True)
class _LabeledSample:
    trade_date: date
    mti: float
    msi: float
    rsk: float
    delta_mti: float
    delta_msi: float
    y_env_continue: int | None
    y_mainline_expand: int | None
    y_risk_event: int | None
    y_red_next: float | None
    y_tradable_up_next: float | None


class _BucketProbabilityModel:
    def __init__(self, *, min_state_samples: int = 30) -> None:
        self.min_state_samples = min_state_samples
        self.global_rate = 0.5
        self.level_stats: list[dict[tuple[Any, ...], tuple[int, int]]] = [{}, {}, {}, {}]

    def fit(self, samples: list[_LabeledSample], *, label_getter: Callable[[_LabeledSample], int | None]) -> None:
        labeled = [sample for sample in samples if label_getter(sample) is not None]
        if not labeled:
            self.global_rate = 0.5
            self.level_stats = [{}, {}, {}, {}]
            return

        positives = sum(int(label_getter(sample) or 0) for sample in labeled)
        self.global_rate = positives / len(labeled)
        aggregates: list[dict[tuple[Any, ...], list[int]]] = [{}, {}, {}, {}]
        for sample in labeled:
            label = int(label_getter(sample) or 0)
            keys = _state_keys(sample)
            for level, key in enumerate(keys):
                if key not in aggregates[level]:
                    aggregates[level][key] = [0, 0]
                aggregates[level][key][0] += 1
                aggregates[level][key][1] += label

        self.level_stats = [{k: (v[0], v[1]) for k, v in level_map.items()} for level_map in aggregates]

    def predict(self, sample: _LabeledSample) -> float:
        keys = _state_keys(sample)
        min_counts = (
            self.min_state_samples,
            max(15, self.min_state_samples // 2),
            max(10, self.min_state_samples // 3),
            5,
        )
        for level, key in enumerate(keys):
            stats = self.level_stats[level].get(key)
            if stats is None:
                continue
            total, positives = stats
            if total < min_counts[level]:
                continue
            prior_weight = 5.0
            return (positives + self.global_rate * prior_weight) / (total + prior_weight)
        return self.global_rate


class MarketMoodWalkForwardValidationService:
    def __init__(self, *, calculator: MarketMoodCalculator | None = None) -> None:
        self.calculator = calculator or MarketMoodCalculator(sample_threshold=5)

    def run(
        self,
        session: Session,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        exchange: str = "SSE",
        train_days: int = 140,
        valid_days: int = 40,
        test_days: int = 20,
        roll_days: int = 20,
        min_state_samples: int = 30,
        max_signal_days: int | None = None,
        delta_temp: float = 5.0,
        delta_emotion: float = 8.0,
        progress_callback: Callable[[str], None] | None = None,
    ) -> MoodWalkForwardReport:
        if train_days <= 0 or valid_days <= 0 or test_days <= 0 or roll_days <= 0:
            raise ValueError("train_days/valid_days/test_days/roll_days must all be > 0")
        common_dates = self._load_common_trade_dates(
            session,
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
        )
        if not common_dates:
            raise ValueError("no common trade dates available under current filters")
        if max_signal_days is not None and max_signal_days > 0 and len(common_dates) > max_signal_days:
            common_dates = common_dates[-max_signal_days:]

        snapshots = []
        total_days = len(common_dates)
        for index, trade_day in enumerate(common_dates, start=1):
            if progress_callback is not None:
                progress_callback(f"mood_snapshot: {index}/{total_days} trade_date={trade_day.isoformat()}")
            snapshots.append(
                self.calculator.calculate_for_trade_date(
                    session,
                    trade_date=trade_day,
                    exchange=exchange,
                )
            )
        rows = self._build_score_rows(snapshots)
        samples = self._build_labeled_samples(
            rows,
            delta_temp=delta_temp,
            delta_emotion=delta_emotion,
        )
        if not samples:
            raise ValueError("not enough samples after label construction")

        folds, points = self._run_walk_forward(
            samples=samples,
            train_days=train_days,
            valid_days=valid_days,
            test_days=test_days,
            roll_days=roll_days,
            min_state_samples=min_state_samples,
        )
        if not folds:
            raise ValueError("not enough signal days for the configured walk-forward window")

        aggregate_metrics = self._aggregate_metrics(points)
        playbook_distribution = self._playbook_distribution(points)
        return MoodWalkForwardReport(
            common_start_date=common_dates[0],
            common_end_date=common_dates[-1],
            common_days=len(common_dates),
            signal_days=len(samples),
            folds=folds,
            aggregate_metrics=aggregate_metrics,
            playbook_distribution=playbook_distribution,
            points=points,
        )

    def _load_common_trade_dates(
        self,
        session: Session,
        *,
        exchange: str,
        start_date: date | None,
        end_date: date | None,
    ) -> list[date]:
        stmt = select(TradeCalendar.trade_date).where(
            TradeCalendar.exchange == exchange,
            TradeCalendar.is_open.is_(True),
            exists(
                select(1).where(
                    EquityDailyBar.trade_date == TradeCalendar.trade_date,
                )
            ),
            exists(
                select(1).where(
                    EquityStkLimit.trade_date == TradeCalendar.trade_date,
                )
            ),
            exists(
                select(1).where(
                    EquityAdjFactor.trade_date == TradeCalendar.trade_date,
                )
            ),
            exists(
                select(1).where(
                    EquityDailyBasic.trade_date == TradeCalendar.trade_date,
                )
            ),
            exists(
                select(1).where(
                    IndexDailyServing.trade_date == TradeCalendar.trade_date,
                )
            ),
            exists(
                select(1).where(
                    and_(
                        DcIndex.trade_date == TradeCalendar.trade_date,
                        DcIndex.idx_type == "概念板块",
                    )
                )
            ),
            exists(
                select(1).where(
                    DcMember.trade_date == TradeCalendar.trade_date,
                )
            ),
        )
        if start_date is not None:
            stmt = stmt.where(TradeCalendar.trade_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(TradeCalendar.trade_date <= end_date)
        stmt = stmt.order_by(TradeCalendar.trade_date)
        return list(session.scalars(stmt))

    def _build_score_rows(self, snapshots: list) -> list[_ScoreRow]:  # type: ignore[no-untyped-def]
        rows: list[_ScoreRow] = []
        previous_row: _ScoreRow | None = None
        for snapshot in snapshots:
            temperature = snapshot.temperature
            emotion = snapshot.emotion

            mti = _build_mti_score(temperature=temperature)
            msi = _build_msi_score(emotion=emotion)
            rsk = _build_rsk_score(
                high_collapse_rate=_to_float(temperature.get("high_collapse_rate")),
                blast_rate=_to_float(emotion.get("blast_rate")),
                limit_down_rate=_to_float(temperature.get("limit_down_rate")),
            )

            delta_mti = 0.0 if previous_row is None else mti - previous_row.mti
            delta_msi = 0.0 if previous_row is None else msi - previous_row.msi
            delta_rsk = 0.0 if previous_row is None else rsk - previous_row.rsk

            row = _ScoreRow(
                trade_date=snapshot.trade_date,
                mti=mti,
                msi=msi,
                rsk=rsk,
                delta_mti=delta_mti,
                delta_msi=delta_msi,
                delta_rsk=delta_rsk,
                red_rate=_to_float(temperature.get("red_rate")),
                tradable_up_rate=_to_float(emotion.get("tradable_up_rate")),
                mainline_concentration=_to_float(temperature.get("mainline_concentration")),
                high_collapse_rate=_to_float(temperature.get("high_collapse_rate")),
                blast_rate=_to_float(emotion.get("blast_rate")),
                limit_down_rate=_to_float(temperature.get("limit_down_rate")),
            )
            rows.append(row)
            previous_row = row
        return rows

    def _build_labeled_samples(
        self,
        rows: list[_ScoreRow],
        *,
        delta_temp: float,
        delta_emotion: float,
    ) -> list[_LabeledSample]:
        if len(rows) < 2:
            return []

        risk_thresholds: list[tuple[float | None, float | None, float | None]] = []
        for idx in range(len(rows)):
            history = rows[max(0, idx - 252) : idx]
            high_values = [item.high_collapse_rate for item in history if item.high_collapse_rate is not None]
            blast_values = [item.blast_rate for item in history if item.blast_rate is not None]
            down_values = [item.limit_down_rate for item in history if item.limit_down_rate is not None]
            risk_thresholds.append(
                (
                    _quantile(high_values, 0.8) if len(high_values) >= 20 else None,
                    _quantile(blast_values, 0.8) if len(blast_values) >= 20 else None,
                    _quantile(down_values, 0.8) if len(down_values) >= 20 else None,
                )
            )

        samples: list[_LabeledSample] = []
        for idx in range(len(rows) - 1):
            current = rows[idx]
            next_row = rows[idx + 1]
            y_temp_cont = int(next_row.mti >= current.mti - delta_temp)
            y_emo_cont = int(next_row.msi >= current.msi - delta_emotion)
            y_env_cont = int(y_temp_cont == 1 and y_emo_cont == 1)

            y_mainline_expand: int | None = None
            if current.mainline_concentration is not None and next_row.mainline_concentration is not None:
                y_mainline_expand = int(next_row.mainline_concentration >= current.mainline_concentration - 0.005)

            y_risk_event: int | None = None
            q_high, q_blast, q_down = risk_thresholds[idx + 1]
            if (
                q_high is not None
                and q_blast is not None
                and q_down is not None
                and next_row.high_collapse_rate is not None
                and next_row.blast_rate is not None
                and next_row.limit_down_rate is not None
            ):
                y_risk_event = int(
                    next_row.high_collapse_rate > q_high
                    or next_row.blast_rate > q_blast
                    or next_row.limit_down_rate > q_down
                )

            samples.append(
                _LabeledSample(
                    trade_date=current.trade_date,
                    mti=current.mti,
                    msi=current.msi,
                    rsk=current.rsk,
                    delta_mti=current.delta_mti,
                    delta_msi=current.delta_msi,
                    y_env_continue=y_env_cont,
                    y_mainline_expand=y_mainline_expand,
                    y_risk_event=y_risk_event,
                    y_red_next=next_row.red_rate,
                    y_tradable_up_next=next_row.tradable_up_rate,
                )
            )
        return samples

    def _run_walk_forward(
        self,
        *,
        samples: list[_LabeledSample],
        train_days: int,
        valid_days: int,
        test_days: int,
        roll_days: int,
        min_state_samples: int,
    ) -> tuple[list[MoodWalkForwardFold], list[MoodWalkForwardPoint]]:
        folds: list[MoodWalkForwardFold] = []
        points: list[MoodWalkForwardPoint] = []
        fold_index = 0
        while True:
            train_end = train_days + fold_index * roll_days
            valid_start = train_end
            valid_end = valid_start + valid_days
            test_start = valid_end
            test_end = test_start + test_days
            if test_end > len(samples):
                break

            train_slice = samples[:train_end]
            valid_slice = samples[valid_start:valid_end]
            test_slice = samples[test_start:test_end]
            if not train_slice or not valid_slice or not test_slice:
                break

            env_model = _BucketProbabilityModel(min_state_samples=min_state_samples)
            main_model = _BucketProbabilityModel(min_state_samples=min_state_samples)
            risk_model = _BucketProbabilityModel(min_state_samples=min_state_samples)
            env_model.fit(train_slice, label_getter=lambda item: item.y_env_continue)
            main_model.fit(train_slice, label_getter=lambda item: item.y_mainline_expand)
            risk_model.fit(train_slice, label_getter=lambda item: item.y_risk_event)

            fold_points: list[MoodWalkForwardPoint] = []
            for sample in test_slice:
                p_env = env_model.predict(sample)
                p_main = main_model.predict(sample)
                p_risk = risk_model.predict(sample)

                base_exposure = _clip(0.15 + 0.45 * p_env + 0.20 * p_main - 0.50 * p_risk, 0.0, 0.80)
                playbook = _rule_engine(sample=sample, p_env=p_env, p_main=p_main, p_risk=p_risk)
                exposure = min(base_exposure, _playbook_cap(playbook))
                allow_chase = bool(55.0 <= sample.msi <= 75.0 and sample.rsk < 60.0 and p_risk < 0.35)

                fold_points.append(
                    MoodWalkForwardPoint(
                        trade_date=sample.trade_date,
                        fold_index=fold_index + 1,
                        mti=sample.mti,
                        msi=sample.msi,
                        rsk=sample.rsk,
                        p_env_continue=p_env,
                        p_mainline_expand=p_main,
                        p_risk_event=p_risk,
                        y_env_continue=sample.y_env_continue,
                        y_mainline_expand=sample.y_mainline_expand,
                        y_risk_event=sample.y_risk_event,
                        y_red_next=sample.y_red_next,
                        y_tradable_up_next=sample.y_tradable_up_next,
                        recommended_playbook=playbook,
                        recommended_exposure=exposure,
                        allow_chase=allow_chase,
                        fallback_level="rule_engine_v1",
                    )
                )
            points.extend(fold_points)

            env_brier = _brier(
                preds=[item.p_env_continue for item in fold_points if item.y_env_continue is not None],
                labels=[item.y_env_continue for item in fold_points if item.y_env_continue is not None],
            )
            main_brier = _brier(
                preds=[item.p_mainline_expand for item in fold_points if item.y_mainline_expand is not None],
                labels=[item.y_mainline_expand for item in fold_points if item.y_mainline_expand is not None],
            )
            risk_brier = _brier(
                preds=[item.p_risk_event for item in fold_points if item.y_risk_event is not None],
                labels=[item.y_risk_event for item in fold_points if item.y_risk_event is not None],
            )
            mti_red_rank_ic = _spearman(
                [item.mti for item in fold_points if item.y_red_next is not None],
                [item.y_red_next for item in fold_points if item.y_red_next is not None],
            )
            msi_tradable_up_rank_ic = _spearman(
                [item.msi for item in fold_points if item.y_tradable_up_next is not None],
                [item.y_tradable_up_next for item in fold_points if item.y_tradable_up_next is not None],
            )

            folds.append(
                MoodWalkForwardFold(
                    fold_index=fold_index + 1,
                    train_start=train_slice[0].trade_date,
                    train_end=train_slice[-1].trade_date,
                    valid_start=valid_slice[0].trade_date,
                    valid_end=valid_slice[-1].trade_date,
                    test_start=test_slice[0].trade_date,
                    test_end=test_slice[-1].trade_date,
                    train_size=len(train_slice),
                    valid_size=len(valid_slice),
                    test_size=len(test_slice),
                    env_brier=env_brier,
                    main_brier=main_brier,
                    risk_brier=risk_brier,
                    mti_red_rank_ic=mti_red_rank_ic,
                    msi_tradable_up_rank_ic=msi_tradable_up_rank_ic,
                )
            )
            fold_index += 1
        return folds, points

    @staticmethod
    def _aggregate_metrics(points: list[MoodWalkForwardPoint]) -> dict[str, float | None]:
        env_pairs = [(item.p_env_continue, item.y_env_continue) for item in points if item.y_env_continue is not None]
        main_pairs = [(item.p_mainline_expand, item.y_mainline_expand) for item in points if item.y_mainline_expand is not None]
        risk_pairs = [(item.p_risk_event, item.y_risk_event) for item in points if item.y_risk_event is not None]

        return {
            "env_brier": _brier([item[0] for item in env_pairs], [item[1] for item in env_pairs]),
            "main_brier": _brier([item[0] for item in main_pairs], [item[1] for item in main_pairs]),
            "risk_brier": _brier([item[0] for item in risk_pairs], [item[1] for item in risk_pairs]),
            "mti_red_rank_ic": _spearman(
                [item.mti for item in points if item.y_red_next is not None],
                [item.y_red_next for item in points if item.y_red_next is not None],
            ),
            "msi_tradable_up_rank_ic": _spearman(
                [item.msi for item in points if item.y_tradable_up_next is not None],
                [item.y_tradable_up_next for item in points if item.y_tradable_up_next is not None],
            ),
            "avg_recommended_exposure": mean([item.recommended_exposure for item in points]) if points else None,
        }

    @staticmethod
    def _playbook_distribution(points: list[MoodWalkForwardPoint]) -> dict[str, int]:
        distribution = {"A0": 0, "A1": 0, "A2": 0, "A3": 0, "A4": 0}
        for item in points:
            if item.recommended_playbook in distribution:
                distribution[item.recommended_playbook] += 1
        return distribution


def _build_mti_score(*, temperature: dict[str, Any]) -> float:
    red_rate = _to_float(temperature.get("red_rate"))
    median_return = _to_float(temperature.get("median_return"))
    strong3_rate = _to_float(temperature.get("strong3_rate"))
    weak3_rate = _to_float(temperature.get("weak3_rate"))
    amount_ratio = _to_float(temperature.get("market_amount_ratio_20"))
    small_vs_large = _to_float(temperature.get("small_vs_large"))
    concentration = _to_float(temperature.get("mainline_concentration"))
    limit_down_rate = _to_float(temperature.get("limit_down_rate"))
    high_collapse_rate = _to_float(temperature.get("high_collapse_rate"))

    score = (
        0.18 * _n_pos(red_rate, 0.35, 0.85)
        + 0.16 * _n_pos(median_return, -0.03, 0.03)
        + 0.10 * _n_pos(strong3_rate, 0.00, 0.25)
        + 0.10 * _n_neg(weak3_rate, 0.00, 0.15)
        + 0.12 * _n_pos(amount_ratio, 0.80, 1.40)
        + 0.08 * _n_pos(small_vs_large, -0.03, 0.03)
        + 0.10 * _n_pos(concentration, 0.00, 0.20)
        + 0.08 * _n_neg(limit_down_rate, 0.00, 0.03)
        + 0.08 * _n_neg(high_collapse_rate, 0.00, 0.12)
    )
    return _clip(score * 100.0, 0.0, 100.0)


def _build_msi_score(*, emotion: dict[str, Any]) -> float:
    tradable_up_rate = _to_float(emotion.get("tradable_up_rate"))
    seal_success_rate = _to_float(emotion.get("seal_success_rate"))
    blast_rate = _to_float(emotion.get("blast_rate"))
    board2plus_rate = _to_float(emotion.get("board2plus_rate"))
    max_board = _to_float(emotion.get("max_board"))
    advance_rate = _to_float(emotion.get("advance_rate"))
    close_premium = _to_float(emotion.get("close_premium"))
    big_loss_rate = _to_float(emotion.get("big_loss_rate"))
    high_board_break_kill_rate = _to_float(emotion.get("high_board_break_kill_rate"))

    score = (
        0.18 * _n_pos(tradable_up_rate, 0.00, 0.06)
        + 0.16 * _n_pos(seal_success_rate, 0.40, 1.00)
        + 0.12 * _n_neg(blast_rate, 0.00, 0.60)
        + 0.10 * _n_pos(board2plus_rate, 0.00, 0.03)
        + 0.10 * _n_pos(max_board, 0.00, 8.00)
        + 0.12 * _n_pos(advance_rate, 0.00, 0.50)
        + 0.10 * _n_pos(close_premium, -0.03, 0.05)
        + 0.07 * _n_neg(big_loss_rate, 0.00, 0.40)
        + 0.05 * _n_neg(high_board_break_kill_rate, 0.00, 0.60)
    )
    return _clip(score * 100.0, 0.0, 100.0)


def _build_rsk_score(
    *,
    high_collapse_rate: float | None,
    blast_rate: float | None,
    limit_down_rate: float | None,
) -> float:
    score = (
        0.40 * _n_pos(high_collapse_rate, 0.00, 0.20)
        + 0.35 * _n_pos(blast_rate, 0.00, 0.60)
        + 0.25 * _n_pos(limit_down_rate, 0.00, 0.04)
    )
    return _clip(score * 100.0, 0.0, 100.0)


def _state_keys(sample: _LabeledSample) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]]:
    mti_bucket = _bucket(sample.mti, low=40.0, high=65.0)
    msi_bucket = _bucket(sample.msi, low=35.0, high=70.0)
    rsk_bucket = _bucket(sample.rsk, low=45.0, high=65.0)
    d_mti = _sign(sample.delta_mti)
    d_msi = _sign(sample.delta_msi)
    return (
        (mti_bucket, msi_bucket, rsk_bucket, d_mti, d_msi),
        (mti_bucket, msi_bucket, rsk_bucket),
        (mti_bucket, msi_bucket),
        (mti_bucket,),
    )


def _rule_engine(*, sample: _LabeledSample, p_env: float, p_main: float, p_risk: float) -> str:
    _ = p_main
    if p_risk >= 0.60 or sample.rsk >= 70.0:
        return "A4" if sample.mti >= 55.0 else "A0"
    if sample.mti >= 65.0 and 35.0 <= sample.msi < 75.0 and p_env >= 0.55 and p_risk < 0.35:
        return "A2"
    if sample.mti >= 60.0 and sample.msi < 45.0:
        return "A1"
    if sample.mti < 50.0 and sample.msi >= 60.0 and p_risk < 0.40:
        return "A3"
    if sample.mti >= 75.0 and sample.msi >= 75.0 and sample.rsk >= 60.0:
        return "A4"
    return "A1" if sample.mti >= 50.0 else "A0"


def _playbook_cap(playbook: str) -> float:
    caps = {"A0": 0.20, "A1": 0.50, "A2": 0.70, "A3": 0.35, "A4": 0.30}
    return caps.get(playbook, 0.30)


def _bucket(value: float, *, low: float, high: float) -> str:
    if value < low:
        return "low"
    if value < high:
        return "mid"
    return "high"


def _sign(value: float, *, tol: float = 1e-6) -> int:
    if value > tol:
        return 1
    if value < -tol:
        return -1
    return 0


def _brier(preds: list[float], labels: list[int | None]) -> float | None:
    valid_pairs = [(pred, label) for pred, label in zip(preds, labels, strict=False) if label is not None]
    if not valid_pairs:
        return None
    return mean([(pred - float(label)) ** 2 for pred, label in valid_pairs])


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(ys) < 3 or len(xs) != len(ys):
        return None
    x_ranks = _rank_with_ties(xs)
    y_ranks = _rank_with_ties(ys)
    return _pearson(x_ranks, y_ranks)


def _rank_with_ties(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    idx = 0
    while idx < len(indexed):
        j = idx
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[idx][1]:
            j += 1
        avg_rank = (idx + j + 2) / 2.0
        for k in range(idx, j + 1):
            original_index = indexed[k][0]
            ranks[original_index] = avg_rank
        idx = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = mean(xs)
    mean_y = mean(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=False))
    den_x = sum((x - mean_x) ** 2 for x in xs)
    den_y = sum((y - mean_y) ** 2 for y in ys)
    if den_x <= 0.0 or den_y <= 0.0:
        return None
    return num / ((den_x * den_y) ** 0.5)


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    left = floor(pos)
    right = min(left + 1, len(ordered) - 1)
    if left == right:
        return ordered[left]
    weight = pos - left
    return ordered[left] * (1.0 - weight) + ordered[right] * weight


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _n_pos(value: float | None, lo: float, hi: float) -> float:
    if value is None:
        return 0.5
    if hi <= lo:
        return 0.5
    return _clip((value - lo) / (hi - lo), 0.0, 1.0)


def _n_neg(value: float | None, lo: float, hi: float) -> float:
    return 1.0 - _n_pos(value, lo, hi)
