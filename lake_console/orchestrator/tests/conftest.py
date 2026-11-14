"""Explicit test seams; never automatically bypass a production boundary."""

import pytest


@pytest.fixture
def isolated_daily_basic_transport(monkeypatch):
    """Explicit fake pages for unit tests; HTTP integration tests do not use it."""
    from orchestrator.defs.source_readiness import daily_basic

    def fetch(*, tushare, trade_date, offset, fields, base_url, remaining):
        return tushare.call(
            "daily_basic",
            {"trade_date": trade_date.replace("-", ""), "limit": daily_basic.DAILY_BASIC_PAGE_SIZE, "offset": offset},
            fields,
        )

    monkeypatch.setattr(daily_basic, "_fetch_daily_basic_page", fetch)


@pytest.fixture
def isolated_moneyflow_transport(monkeypatch):
    """Existing fake-source tests prove collection/files, not real HTTP expiry.

    Only marked tests request this fixture. The transport-specific integration
    suite deliberately does not use it and exercises owned request processes.
    """
    from orchestrator.defs.source_readiness import moneyflow, moneyflow_daily

    def call(source, api, params, fields, *, deadline, check_cancel):
        check_cancel()
        result = source.call(api, params, fields)
        check_cancel()
        return result

    monkeypatch.setattr(moneyflow, "call_moneyflow_source", call)
    monkeypatch.setattr(moneyflow_daily, "call_moneyflow_source", call)
