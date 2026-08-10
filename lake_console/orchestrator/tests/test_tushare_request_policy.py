import unittest

from orchestrator.defs.tushare_request_policy import (
    TUSHARE_FAILURE_NON_RETRYABLE,
    TUSHARE_FAILURE_RATE_LIMIT,
    TUSHARE_FAILURE_TRANSIENT,
    BoundedCodePageRequestSession,
    TushareRequestPolicy,
    classify_tushare_error,
    execute_bounded_code_pages,
    execute_bounded_code_requests,
    execute_bounded_pages,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class TushareRequestPolicyTests(unittest.TestCase):
    def test_error_classifier_distinguishes_retryable_and_deterministic_errors(self) -> None:
        self.assertEqual(
            classify_tushare_error(RuntimeError("抱歉，您访问接口频率超限(500次/分钟)")),
            (TUSHARE_FAILURE_RATE_LIMIT, True),
        )
        self.assertEqual(
            classify_tushare_error(TimeoutError("timed out")),
            (TUSHARE_FAILURE_TRANSIENT, True),
        )
        self.assertEqual(
            classify_tushare_error(RuntimeError("权限不足，积分不足")),
            (TUSHARE_FAILURE_NON_RETRYABLE, False),
        )

    def test_rate_limit_and_transient_failures_use_bounded_exponential_backoff(self) -> None:
        clock = _FakeClock()
        attempts: dict[str, int] = {}

        def request(code: str) -> list[dict[str, object]]:
            attempts[code] = attempts.get(code, 0) + 1
            if attempts[code] < 3:
                raise RuntimeError("rate limit: 500次/分钟")
            return [{"ts_code": code}]

        result = execute_bounded_code_requests(
            codes=["000001.SZ"],
            request=request,
            extract_rows=lambda response: response,
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.13,
                max_retries=3,
                backoff_base_seconds=1.0,
                backoff_multiplier=2.0,
                max_backoff_seconds=8.0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
            clock=clock.clock,
            sleep_fn=clock.sleep,
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.request_count, 3)
        self.assertEqual(result.retry_count, 2)
        self.assertEqual(clock.sleeps, [1.0, 2.0])

    def test_rate_limiter_enforces_interval_between_code_requests(self) -> None:
        clock = _FakeClock()

        result = execute_bounded_code_requests(
            codes=["000001.SZ", "000002.SZ", "000003.SZ"],
            request=lambda code: [{"ts_code": code}],
            extract_rows=lambda response: response,
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.13,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
            clock=clock.clock,
            sleep_fn=clock.sleep,
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.request_count, 3)
        self.assertEqual(clock.sleeps, [0.13, 0.13])

    def test_empty_response_is_not_a_failure_but_failed_code_blocks_the_day(self) -> None:
        clock = _FakeClock()

        def request(code: str) -> list[dict[str, object]]:
            if code == "000002.SZ":
                raise RuntimeError("invalid ts_code")
            if code == "000003.SZ":
                return []
            return [{"ts_code": code}]

        result = execute_bounded_code_requests(
            codes=["000001.SZ", "000002.SZ", "000003.SZ"],
            request=request,
            extract_rows=lambda response: response,
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=2,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
            clock=clock.clock,
            sleep_fn=clock.sleep,
        )

        self.assertFalse(result.ready)
        self.assertTrue(result.completed)
        self.assertEqual(result.empty_codes, ("000003.SZ",))
        self.assertEqual([failure.code for failure in result.failed_codes], ["000002.SZ"])
        self.assertEqual(result.failed_codes[0].attempts, 1)

    def test_request_and_elapsed_budgets_fail_closed_and_report_unattempted_codes(self) -> None:
        clock = _FakeClock()
        calls: list[str] = []

        def request(code: str) -> list[dict[str, object]]:
            calls.append(code)
            return [{"ts_code": code}]

        result = execute_bounded_code_requests(
            codes=["000001.SZ", "000002.SZ", "000003.SZ"],
            request=request,
            extract_rows=lambda response: response,
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=2,
                max_elapsed_seconds=30.0,
            ),
            clock=clock.clock,
            sleep_fn=clock.sleep,
        )

        self.assertFalse(result.ready)
        self.assertTrue(result.budget_exceeded)
        self.assertEqual(result.budget_reason, "code_scope_exceeds_max_requests")
        self.assertEqual(calls, [])
        self.assertEqual(
            result.unattempted_codes,
            ("000001.SZ", "000002.SZ", "000003.SZ"),
        )
        self.assertEqual(result.to_details()["blocked_reason"], "code_scope_exceeds_max_requests")

    def test_pagination_is_complete_and_uses_the_same_request_budget(self) -> None:
        clock = _FakeClock()
        pages = {
            ("000001.SZ", 0): [{"ts_code": "000001.SZ", "row": 1}, {"row": 2}],
            ("000001.SZ", 2): [{"ts_code": "000001.SZ", "row": 3}],
            ("000002.SZ", 0): [],
        }

        result = execute_bounded_code_pages(
            codes=["000001.SZ", "000002.SZ"],
            request_page=lambda code, offset: pages[(code, offset)],
            extract_rows=lambda response: response,
            page_size=2,
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.13,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
            clock=clock.clock,
            sleep_fn=clock.sleep,
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.page_counts, {"000001.SZ": 2, "000002.SZ": 1})
        self.assertEqual(len(result.rows_by_code["000001.SZ"]), 3)
        self.assertEqual(result.empty_codes, ("000002.SZ",))
        self.assertEqual(result.request_count, 3)
        self.assertEqual(clock.sleeps, [0.13, 0.13])

    def test_duplicate_or_empty_code_scope_is_rejected(self) -> None:
        policy = TushareRequestPolicy()
        for codes in (["000001.SZ", "000001.SZ"], ["000001.SZ", ""]):
            with self.assertRaises(ValueError):
                execute_bounded_code_requests(
                    codes=codes,
                    request=lambda code: [],
                    extract_rows=lambda response: response,
                    policy=policy,
                )

    def test_code_scope_over_request_budget_fails_before_first_request(self) -> None:
        calls = []
        result = execute_bounded_code_pages(
            codes=["BK0001.DC", "BK0002.DC", "BK0003.DC"],
            request_page=lambda code, _offset: calls.append(code) or [],
            extract_rows=lambda response: response,
            page_size=5_000,
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=2,
                max_elapsed_seconds=30.0,
            ),
        )

        self.assertFalse(result.ready)
        self.assertEqual(result.budget_reason, "code_scope_exceeds_max_requests")
        self.assertEqual(result.request_count, 0)
        self.assertEqual(calls, [])

    def test_generic_pagination_requests_empty_terminal_page_after_full_page(self) -> None:
        clock = _FakeClock()
        pages = {
            0: [{"id": 1}, {"id": 2}],
            2: [],
        }

        result = execute_bounded_pages(
            request_page=lambda offset: pages[offset],
            extract_rows=lambda response: response,
            page_size=2,
            scope="dc_daily:2026-07-14",
            row_key=lambda row: row["id"],
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=5,
                max_elapsed_seconds=30.0,
            ),
            clock=clock.clock,
            sleep_fn=clock.sleep,
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.page_offsets, (0, 2))
        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.rows, ({"id": 1}, {"id": 2}))

    def test_generic_pagination_can_stream_pages_without_retaining_rows(self) -> None:
        consumed_pages: list[tuple[int, tuple[int, ...]]] = []
        pages = {
            0: [{"id": 1}, {"id": 2}],
            2: [{"id": 3}],
        }

        result = execute_bounded_pages(
            request_page=lambda offset: pages[offset],
            extract_rows=lambda response: response,
            page_size=2,
            scope="idx_factor_pro:2026-08-07",
            row_key=lambda row: row["id"],
            consume_page=lambda offset, rows: consumed_pages.append(
                (offset, tuple(int(row["id"]) for row in rows))
            ),
            retain_rows=False,
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=5,
                max_elapsed_seconds=30.0,
            ),
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.rows, ())
        self.assertEqual(consumed_pages, [(0, (1, 2)), (2, (3,))])

    def test_generic_pagination_rejects_duplicate_rows_across_pages(self) -> None:
        result = execute_bounded_pages(
            request_page=lambda offset: (
                [{"id": 1}, {"id": 2}]
                if offset == 0
                else [{"id": 2}, {"id": 3}]
            ),
            extract_rows=lambda response: response,
            page_size=2,
            scope="dc_index:行业板块",
            row_key=lambda row: row["id"],
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=5,
                max_elapsed_seconds=30.0,
            ),
        )

        self.assertFalse(result.ready)
        self.assertEqual(result.blocked_reason, "page_request_failed")
        self.assertIn("duplicate row", result.failed_pages[0].message)

    def test_code_pagination_rejects_duplicate_key_across_pages(self) -> None:
        result = execute_bounded_code_pages(
            codes=["000001.SZ"],
            request_page=lambda _code, offset: (
                [{"id": 1}, {"id": 2}]
                if offset == 0
                else [{"id": 2}, {"id": 3}]
            ),
            extract_rows=lambda response: response,
            page_size=2,
            row_key=lambda row: row["id"],
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=5,
                max_elapsed_seconds=30.0,
            ),
        )

        self.assertFalse(result.ready)
        self.assertEqual(result.failed_codes[0].code, "000001.SZ")

    def test_code_page_session_shares_rate_limit_and_request_budget_across_batches(self) -> None:
        clock = _FakeClock()
        calls: list[str] = []
        session = BoundedCodePageRequestSession(
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.13,
                max_retries=0,
                max_requests=3,
                max_elapsed_seconds=30.0,
            ),
            clock=clock.clock,
            sleep_fn=clock.sleep,
        )

        first_result = session.execute(
            codes=["BK0001.DC", "BK0002.DC"],
            request_page=lambda code, _offset: calls.append(code) or [{"ts_code": code}],
            extract_rows=lambda response: response,
            page_size=5_000,
        )
        second_result = session.execute(
            codes=["BK0003.DC"],
            request_page=lambda code, _offset: calls.append(code) or [{"ts_code": code}],
            extract_rows=lambda response: response,
            page_size=5_000,
        )
        exhausted_result = session.execute(
            codes=["BK0004.DC"],
            request_page=lambda code, _offset: calls.append(code) or [{"ts_code": code}],
            extract_rows=lambda response: response,
            page_size=5_000,
        )

        self.assertTrue(first_result.ready)
        self.assertTrue(second_result.ready)
        self.assertEqual(first_result.request_count, 2)
        self.assertEqual(second_result.request_count, 1)
        self.assertEqual(session.request_count, 3)
        self.assertEqual(session.remaining_request_count, 0)
        self.assertEqual(calls, ["BK0001.DC", "BK0002.DC", "BK0003.DC"])
        self.assertEqual(clock.sleeps, [0.13, 0.13])
        self.assertFalse(exhausted_result.ready)
        self.assertEqual(
            exhausted_result.budget_reason,
            "code_scope_exceeds_remaining_request_budget",
        )

    def test_code_page_session_shares_elapsed_time_budget_across_batches(self) -> None:
        clock = _FakeClock()
        calls: list[str] = []
        session = BoundedCodePageRequestSession(
            policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=3,
                max_elapsed_seconds=30.0,
            ),
            clock=clock.clock,
            sleep_fn=clock.sleep,
        )

        first_result = session.execute(
            codes=["BK0001.DC"],
            request_page=lambda code, _offset: calls.append(code) or [{"ts_code": code}],
            extract_rows=lambda response: response,
            page_size=5_000,
        )
        clock.now = 30.0
        second_result = session.execute(
            codes=["BK0002.DC"],
            request_page=lambda code, _offset: calls.append(code) or [{"ts_code": code}],
            extract_rows=lambda response: response,
            page_size=5_000,
        )

        self.assertTrue(first_result.ready)
        self.assertFalse(second_result.ready)
        self.assertEqual(second_result.budget_reason, "max_elapsed_seconds_exceeded")
        self.assertEqual(session.request_count, 1)
        self.assertEqual(calls, ["BK0001.DC"])


if __name__ == "__main__":
    unittest.main()
