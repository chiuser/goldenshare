import unittest

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
)
from orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_repair_job_sensor import (
    _run_request_for_repair_decision,
    build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision,
    gold_stk_mins_qfq_macd_kdj_repair_job_sensor,
)


TRADE_DATE = "2026-06-05"
REPAIR_START_DATE = "2014-01-02"
REPAIR_CODES_HASH = "b" * 64


def _qfq_status(
    *,
    requires_macd_kdj_repair: bool,
    code_count: int,
    truncated: bool = False,
    codes: tuple[str, ...] | None = None,
) -> GoldStkMinsQfqFactorRepairStatus:
    if codes is None:
        codes = tuple(f"{index:06d}.SZ" for index in range(code_count))
    return GoldStkMinsQfqFactorRepairStatus(
        ready=True,
        trade_date=TRADE_DATE,
        reason="ready",
        repair_required=requires_macd_kdj_repair,
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


class StkMinsQfqM12RepairSensorContractTests(unittest.TestCase):
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
        self.assertEqual(op_config["start_trade_date"], REPAIR_START_DATE)
        self.assertEqual(op_config["stock_codes"], ["000001.SZ", "600000.SH"])
        self.assertEqual(op_config["repair_required_codes_hash"], REPAIR_CODES_HASH)
        self.assertEqual(
            op_config["source_qfq_factor_repair_event_storage_ids"],
            [101, 102, 103, 104, 105, 106, 107],
        )
        self.assertIn(TRADE_DATE, request.run_key)
        self.assertIn(REPAIR_CODES_HASH, request.run_key)

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
