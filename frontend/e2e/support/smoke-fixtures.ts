import type { Page, Route } from "@playwright/test";

type SmokeScenario = "ops-overview" | "task-records" | "review-index" | "share-market";

const AUTH_TOKEN_KEY = "goldenshare.frontend.auth.token";
const AUTH_REFRESH_TOKEN_KEY = "goldenshare.frontend.auth.refresh-token";

const adminUser = {
  id: 1,
  username: "admin",
  display_name: "系统管理员",
  is_admin: true,
  roles: ["admin"],
};

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function mockOpsOverview(route: Route, pathname: string) {
  if (pathname === "/api/v1/ops/overview") {
    return fulfillJson(route, {
      today_kpis: {
        business_date: "2026-04-17",
        total_requests: 8,
        completed_requests: 6,
        running_requests: 1,
        failed_requests: 1,
        queued_requests: 0,
        attention_dataset_count: 2,
      },
      kpis: {
        total_executions: 8,
        queued_executions: 0,
        running_executions: 1,
        success_executions: 6,
        failed_executions: 1,
        canceled_executions: 0,
        partial_success_executions: 0,
      },
      freshness_summary: {
        total_datasets: 24,
        fresh_datasets: 20,
        lagging_datasets: 2,
        stale_datasets: 1,
        unknown_datasets: 1,
        disabled_datasets: 0,
      },
      lagging_datasets: [],
      recent_executions: [],
      recent_failures: [],
    });
  }

  if (pathname === "/api/v1/ops/pipeline-modes") {
    return fulfillJson(route, {
      total: 2,
      items: [
        {
          dataset_key: "daily",
          display_name: "股票日线",
          domain_key: "equity",
          domain_display_name: "股票",
          mode: "single_source_direct",
          source_scope: "tushare",
          layer_plan: "raw,serving",
          raw_table: "raw_tushare.equity_daily_bar",
          std_table_hint: null,
          serving_table: "core_serving.equity_daily_bar",
          freshness_status: "fresh",
          latest_business_date: "2026-04-16",
          std_mapping_configured: true,
          std_cleansing_configured: true,
          resolution_policy_configured: true,
        },
        {
          dataset_key: "moneyflow_dc",
          display_name: "板块资金流向（东财）",
          domain_key: "moneyflow",
          domain_display_name: "资金流向",
          mode: "multi_source_pipeline",
          source_scope: "dc",
          layer_plan: "raw,std,resolution,serving",
          raw_table: "raw_dc.moneyflow_ind_dc",
          std_table_hint: "std.moneyflow_ind_dc",
          serving_table: "core_serving.moneyflow_ind_dc",
          freshness_status: "lagging",
          latest_business_date: "2026-04-15",
          std_mapping_configured: true,
          std_cleansing_configured: false,
          resolution_policy_configured: true,
        },
      ],
    });
  }

  if (pathname === "/api/v1/ops/layer-snapshots/latest") {
    return fulfillJson(route, {
      total: 6,
      items: [
        {
          snapshot_date: "2026-04-17",
          dataset_key: "daily",
          source_key: "tushare",
          stage: "raw",
          status: "success",
          rows_in: 5120,
          rows_out: 5120,
          error_count: 0,
          lag_seconds: 0,
          message: null,
          calculated_at: "2026-04-17T09:00:00+08:00",
          last_success_at: "2026-04-17T09:00:00+08:00",
          last_failure_at: null,
        },
        {
          snapshot_date: "2026-04-17",
          dataset_key: "daily",
          source_key: null,
          stage: "serving",
          status: "success",
          rows_in: 5120,
          rows_out: 5120,
          error_count: 0,
          lag_seconds: 0,
          message: null,
          calculated_at: "2026-04-17T09:03:00+08:00",
          last_success_at: "2026-04-17T09:03:00+08:00",
          last_failure_at: null,
        },
        {
          snapshot_date: "2026-04-17",
          dataset_key: "moneyflow_dc",
          source_key: "dc",
          stage: "raw",
          status: "success",
          rows_in: 380,
          rows_out: 380,
          error_count: 0,
          lag_seconds: 0,
          message: null,
          calculated_at: "2026-04-17T08:40:00+08:00",
          last_success_at: "2026-04-17T08:40:00+08:00",
          last_failure_at: null,
        },
        {
          snapshot_date: "2026-04-17",
          dataset_key: "moneyflow_dc",
          source_key: null,
          stage: "std",
          status: "success",
          rows_in: 380,
          rows_out: 380,
          error_count: 0,
          lag_seconds: 0,
          message: null,
          calculated_at: "2026-04-17T08:43:00+08:00",
          last_success_at: "2026-04-17T08:43:00+08:00",
          last_failure_at: null,
        },
        {
          snapshot_date: "2026-04-17",
          dataset_key: "moneyflow_dc",
          source_key: null,
          stage: "resolution",
          status: "warning",
          rows_in: 380,
          rows_out: 372,
          error_count: 1,
          lag_seconds: 0,
          message: "部分记录待复核",
          calculated_at: "2026-04-17T08:47:00+08:00",
          last_success_at: "2026-04-17T08:47:00+08:00",
          last_failure_at: null,
        },
        {
          snapshot_date: "2026-04-17",
          dataset_key: "moneyflow_dc",
          source_key: null,
          stage: "serving",
          status: "warning",
          rows_in: 372,
          rows_out: 372,
          error_count: 0,
          lag_seconds: 0,
          message: "最近业务日滞后 1 天",
          calculated_at: "2026-04-17T08:50:00+08:00",
          last_success_at: "2026-04-17T08:50:00+08:00",
          last_failure_at: null,
        },
      ],
    });
  }

  return fulfillJson(route, { detail: `unhandled api: ${pathname}` }, 404);
}

function mockTaskRecords(route: Route, pathname: string) {
  if (pathname === "/api/v1/ops/catalog") {
    return fulfillJson(route, {
      job_specs: [
        { key: "sync_daily.daily", display_name: "股票日线同步" },
        { key: "moneyflow_ind_dc", display_name: "板块资金流向（东财）" },
      ],
      workflow_specs: [],
    });
  }

  if (pathname === "/api/v1/ops/executions") {
    return fulfillJson(route, {
      total: 2,
      items: [
        {
          id: 101,
          spec_type: "job",
          spec_key: "sync_daily.daily",
          spec_display_name: "股票日线同步",
          schedule_display_name: null,
          trigger_source: "manual",
          status: "running",
          requested_by_username: "admin",
          requested_at: "2026-04-17T09:30:00+08:00",
          started_at: "2026-04-17T09:30:02+08:00",
          ended_at: null,
          rows_fetched: 5200,
          rows_written: 5100,
          progress_current: 68,
          progress_total: 120,
          progress_percent: 57,
          progress_message: "daily: 68/120 trade_date=20260417 fetched=5200 written=5100",
          last_progress_at: "2026-04-17T09:36:00+08:00",
          summary_message: "正在汇总最新交易日数据",
          error_code: null,
        },
        {
          id: 102,
          spec_type: "job",
          spec_key: "moneyflow_ind_dc",
          spec_display_name: "板块资金流向（东财）",
          schedule_display_name: null,
          trigger_source: "scheduled",
          status: "failed",
          requested_by_username: "system",
          requested_at: "2026-04-17T08:40:00+08:00",
          started_at: "2026-04-17T08:40:03+08:00",
          ended_at: "2026-04-17T08:41:12+08:00",
          rows_fetched: 0,
          rows_written: 0,
          progress_current: 0,
          progress_total: 0,
          progress_percent: 0,
          progress_message: null,
          last_progress_at: "2026-04-17T08:40:40+08:00",
          summary_message: "上游接口超时，等待人工重试",
          error_code: "upstream_timeout",
        },
      ],
    });
  }

  return fulfillJson(route, { detail: `unhandled api: ${pathname}` }, 404);
}

function mockReviewIndex(route: Route, pathname: string) {
  if (pathname === "/api/v1/ops/review/index/active") {
    return fulfillJson(route, {
      total: 2,
      page: 1,
      page_size: 50,
      items: [
        {
          resource: "index_daily",
          ts_code: "000300.SH",
          index_name: "沪深300",
          first_seen_date: "2026-01-02",
          last_seen_date: "2026-04-17",
          last_checked_at: "2026-04-17T09:10:00+08:00",
        },
        {
          resource: "index_daily",
          ts_code: "000905.SH",
          index_name: "中证500",
          first_seen_date: "2026-01-03",
          last_seen_date: "2026-04-17",
          last_checked_at: "2026-04-17T09:10:00+08:00",
        },
      ],
    });
  }

  return fulfillJson(route, { detail: `unhandled api: ${pathname}` }, 404);
}

function mockShareMarket(route: Route, pathname: string) {
  if (pathname === "/api/v1/share/market-overview") {
    return fulfillJson(route, {
      available: true,
      unavailable_reason: null,
      summary: {
        as_of_date: "2026-04-17",
        total_symbols: 5236,
        up_count: 3120,
        down_count: 1892,
        avg_pct_change: "1.26",
        total_amount: "1289000000000",
      },
      top_by_amount: [
        { ts_code: "600519.SH", name: "贵州茅台", trade_date: "2026-04-17", close: "1820.50", pct_change: "2.35", amount: "12450000000" },
        { ts_code: "300750.SZ", name: "宁德时代", trade_date: "2026-04-17", close: "268.40", pct_change: "-1.12", amount: "9860000000" },
      ],
      top_gainers: [
        { ts_code: "688256.SH", name: "寒武纪", trade_date: "2026-04-17", close: "328.10", pct_change: "12.24", amount: "5620000000" },
        { ts_code: "002594.SZ", name: "比亚迪", trade_date: "2026-04-17", close: "255.80", pct_change: "8.51", amount: "7340000000" },
      ],
      top_losers: [
        { ts_code: "601012.SH", name: "隆基绿能", trade_date: "2026-04-17", close: "18.42", pct_change: "-7.83", amount: "3420000000" },
        { ts_code: "002466.SZ", name: "天齐锂业", trade_date: "2026-04-17", close: "28.16", pct_change: "-6.45", amount: "2910000000" },
      ],
    });
  }

  return fulfillJson(route, { detail: `unhandled api: ${pathname}` }, 404);
}

export async function installApiMocks(page: Page, scenario: SmokeScenario) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;

    if (pathname === "/api/v1/auth/me") {
      return fulfillJson(route, adminUser);
    }

    if (scenario === "ops-overview") {
      return mockOpsOverview(route, pathname);
    }
    if (scenario === "task-records") {
      return mockTaskRecords(route, pathname);
    }
    if (scenario === "review-index") {
      return mockReviewIndex(route, pathname);
    }
    return mockShareMarket(route, pathname);
  });
}

export async function setAdminSession(page: Page) {
  await page.addInitScript(
    ({ tokenKey, refreshTokenKey }) => {
      window.localStorage.setItem(tokenKey, "e2e-admin-token");
      window.localStorage.setItem(refreshTokenKey, "e2e-admin-refresh-token");
    },
    {
      tokenKey: AUTH_TOKEN_KEY,
      refreshTokenKey: AUTH_REFRESH_TOKEN_KEY,
    },
  );
}

export async function stabilizeUi(page: Page) {
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        transition-delay: 0s !important;
        caret-color: transparent !important;
      }

      .app-shell-footer-meta,
      .mantine-Notifications-root {
        visibility: hidden !important;
      }
    `,
  });
  await page.evaluate(async () => {
    if ("fonts" in document) {
      await (document as Document & { fonts: FontFaceSet }).fonts.ready;
    }
  });
  await page.waitForTimeout(150);
}
