import unittest
from types import SimpleNamespace
from unittest.mock import patch

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
)
from orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_repair_job_sensor import (
    _run_request_or_skip_for_repair_decision,
    _run_request_for_repair_decision,
    build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision,
    gold_stk_mins_qfq_macd_kdj_repair_job_sensor,
)


TRADE_DATE = "2026-06-05"
REPAIR_START_DATE = "2014-01-02"
REPAIR_CODES_HASH = "b" * 64
UPSTREAM_BATCH_ID = f"qfq_factor_repair:{TRADE_DATE}:7f3a9c2d8b41"
PRODUCER_RUN_ID = "qfq-factor-repair-run-1"


def _qfq_status(
    *,
    requires_macd_kdj_repair: bool,
    code_count: int,
    truncated: bool = False,
    codes: tuple[str, ...] | None = None,
    upstream_batch_id: str | None = UPSTREAM_BATCH_ID,
) -> GoldStkMinsQfqFactorRepairStatus:
    if codes is None:
        codes = tuple(f"{index:06d}.SZ" for index in range(code_count))
    return GoldStkMinsQfqFactorRepairStatus(
        ready=True,
        trade_date=TRADE_DATE,
        reason="ready",
        repair_required=requires_macd_kdj_repair,
        producer_run_id=PRODUCER_RUN_ID,
        upstream_batch_id=upstream_batch_id,
        qfq_factor_repair_event_storage_ids=(101, 102, 103, 104, 105, 106, 107),
        repair_start_trade_date=REPAIR_START_DATE,
        repair_end_trade_date=TRADE_DATE,
        selected_partition_count=1800,
        repair_required_code_count=code_count,
        repair_required_codes=codes,
        repair_required_codes_hash=REPAIR_CODES_HASH,
        repair_required_codes_truncated=truncated,
        rewritten_file_count=1 if requires_macd_kdj_repair else 0,
        rewritten_row_count=10 if requires_macd_kdj_repair else 0,
    )


class StkMinsQfqMacdKdjRepairSensorContractTests(unittest.TestCase):
    def test_repair_sensor_definition_contract(self) -> None:
        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_repair_job_sensor.name,
            "gold_stk_mins_qfq_macd_kdj_repair_job_sensor",
        )
        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_repair_job_sensor.default_status,
            dg.DefaultSensorStatus.STOPPED,
        )

    def test_zero_code_or_no_history_rewrite_skips(self) -> None:
        decision = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
            target_trade_date=TRADE_DATE,
            qfq_factor_repair_status=_qfq_status(
                requires_macd_kdj_repair=False,
                code_count=0,
                codes=(),
            ),
            macd_kdj_daily_ready=True,
        )

        self.assertIsNone(decision.selected_trade_date)

    def test_one_to_five_hundred_codes_submit_scoped_repair(self) -> None:
        status = _qfq_status(
            requires_macd_kdj_repair=True,
            code_count=2,
            codes=("000001.SZ", "600000.SH"),
        )

        decision = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
            target_trade_date=TRADE_DATE,
            qfq_factor_repair_status=status,
            macd_kdj_daily_ready=True,
        )
        request = _run_request_for_repair_decision(decision)
        op_config = request.run_config["ops"][
            "gold_stk_mins_qfq_macd_kdj_repair_op"
        ]["config"]

        self.assertEqual(decision.selected_trade_date, REPAIR_START_DATE)
        self.assertEqual(decision.upstream_batch_id, UPSTREAM_BATCH_ID)
        self.assertEqual(
            request.run_key,
            f"gold_stk_mins_qfq_macd_kdj_repair:{UPSTREAM_BATCH_ID}",
        )
        self.assertEqual(op_config["qfq_factor_repair_trade_date"], TRADE_DATE)
        self.assertEqual(op_config["start_trade_date"], REPAIR_START_DATE)
        self.assertEqual(op_config["stock_codes"], ["000001.SZ", "600000.SH"])
        self.assertEqual(op_config["repair_required_codes_hash"], REPAIR_CODES_HASH)
        self.assertEqual(op_config["upstream_batch_id"], UPSTREAM_BATCH_ID)
        self.assertNotIn("source_qfq_factor_repair_event_storage_ids", op_config)

    def test_missing_upstream_batch_id_skips(self) -> None:
        decision = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
            target_trade_date=TRADE_DATE,
            qfq_factor_repair_status=_qfq_status(
                requires_macd_kdj_repair=True,
                code_count=2,
                codes=("000001.SZ", "600000.SH"),
                upstream_batch_id=None,
            ),
            macd_kdj_daily_ready=True,
        )

        self.assertIsNone(decision.selected_trade_date)
        self.assertIn("upstream_batch_id", decision.reason)

    def test_upstream_batch_id_is_the_idempotency_key(self) -> None:
        status = _qfq_status(
            requires_macd_kdj_repair=True,
            code_count=2,
            codes=("000001.SZ", "600000.SH"),
        )
        first_decision = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
            target_trade_date=TRADE_DATE,
            qfq_factor_repair_status=status,
            macd_kdj_daily_ready=True,
        )
        repeated_decision = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
            target_trade_date=TRADE_DATE,
            qfq_factor_repair_status=status,
            macd_kdj_daily_ready=True,
        )
        next_batch_decision = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
            target_trade_date=TRADE_DATE,
            qfq_factor_repair_status=_qfq_status(
                requires_macd_kdj_repair=True,
                code_count=2,
                codes=("000001.SZ", "600000.SH"),
                upstream_batch_id=f"qfq_factor_repair:{TRADE_DATE}:nextbatch",
            ),
            macd_kdj_daily_ready=True,
        )

        self.assertEqual(
            _run_request_for_repair_decision(first_decision).run_key,
            _run_request_for_repair_decision(repeated_decision).run_key,
        )
        self.assertNotEqual(
            _run_request_for_repair_decision(first_decision).run_key,
            _run_request_for_repair_decision(next_batch_decision).run_key,
        )

    def test_completion_gate_ready_skips_run_request(self) -> None:
        status = _qfq_status(
            requires_macd_kdj_repair=True,
            code_count=2,
            codes=("000001.SZ", "600000.SH"),
        )
        decision = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
            target_trade_date=TRADE_DATE,
            qfq_factor_repair_status=status,
            macd_kdj_daily_ready=True,
        )

        with (
            patch(
                "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_repair_job_sensor."
                "gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch",
                return_value=SimpleNamespace(ready=True, reason="ready"),
            ),
            patch(
                "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_repair_job_sensor."
                "legacy_gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_qfq_event_storage_ids",
            ) as legacy_gate,
        ):
            result = _run_request_or_skip_for_repair_decision(
                object(),
                decision,
                status,
            )

        self.assertIsInstance(result, dg.SkipReason)
        legacy_gate.assert_not_called()

    def test_legacy_bridge_ready_skips_run_request(self) -> None:
        status = _qfq_status(
            requires_macd_kdj_repair=True,
            code_count=2,
            codes=("000001.SZ", "600000.SH"),
        )
        decision = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
            target_trade_date=TRADE_DATE,
            qfq_factor_repair_status=status,
            macd_kdj_daily_ready=True,
        )

        with (
            patch(
                "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_repair_job_sensor."
                "gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch",
                return_value=SimpleNamespace(ready=False, reason="not ready"),
            ),
            patch(
                "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_repair_job_sensor."
                "legacy_gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_qfq_event_storage_ids",
                return_value=SimpleNamespace(ready=True, reason="legacy ready"),
            ),
        ):
            result = _run_request_or_skip_for_repair_decision(
                object(),
                decision,
                status,
            )

        self.assertIsInstance(result, dg.SkipReason)

    def test_above_five_hundred_or_missing_code_list_skips(self) -> None:
        too_many = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
            target_trade_date=TRADE_DATE,
            qfq_factor_repair_status=_qfq_status(
                requires_macd_kdj_repair=True,
                code_count=501,
                truncated=True,
                codes=(),
            ),
            macd_kdj_daily_ready=True,
        )
        missing_list = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
            target_trade_date=TRADE_DATE,
            qfq_factor_repair_status=_qfq_status(
                requires_macd_kdj_repair=True,
                code_count=2,
                codes=("000001.SZ",),
            ),
            macd_kdj_daily_ready=True,
        )

        self.assertIsNone(too_many.selected_trade_date)
        self.assertIsNone(missing_list.selected_trade_date)

    def test_macd_kdj_daily_not_ready_skips(self) -> None:
        decision = build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision(
            target_trade_date=TRADE_DATE,
            qfq_factor_repair_status=_qfq_status(
                requires_macd_kdj_repair=True,
                code_count=1,
            ),
            macd_kdj_daily_ready=False,
        )

        self.assertIsNone(decision.selected_trade_date)


if __name__ == "__main__":
    unittest.main()
