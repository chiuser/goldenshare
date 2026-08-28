import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { appTheme } from "../app/theme";
import type {
  OpsRealtimeEtfRtDailyHealthResponse,
  OpsRealtimeStockRtDailyHealthResponse,
  OpsRealtimeStockRtMinHealthItem,
  OpsRealtimeStockRtMinHealthResponse,
} from "../shared/api/realtime-types";
import { OpsRealtimeMonitorPage } from "./ops-realtime-monitor-page";

const { apiRequest } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest,
}));

const dailyHealth: OpsRealtimeStockRtDailyHealthResponse = {
  feed_key: "tushare_stock_rt_k",
  display_name: "股票实时日线",
  status: "ok",
  enabled: true,
  redis_connected: true,
  collector_running: true,
  collector_id: "collector-a",
  last_request_at: "2026-06-01T10:00:00+08:00",
  last_success_at: "2026-06-01T10:00:01+08:00",
  last_error_at: null,
  last_error_message: null,
  current_batch_id: "daily-batch-1",
  current_batch_age_seconds: 3,
  current_batch_received_at: "2026-06-01T10:00:01+08:00",
  current_batch_published_at: "2026-06-01T10:00:02+08:00",
  snapshot_count: 5300,
  source_row_count: 5300,
  source_elapsed_ms: 120,
  write_elapsed_ms: 30,
  request_count_last_minute: 5,
  max_calls_per_minute: 20,
  poll_interval_seconds: 6,
  is_trading_day: true,
  collection_sessions: ["09:30-11:30", "13:00-15:00"],
  collection_status: "open",
  stale_after_seconds: 20,
  snapshot_ttl_seconds: 259200,
  keep_recent_batches: 3,
  batch_stream_maxlen: 200,
  delta_stream_maxlen: 1000,
  last_batch_event_id: "1-0",
  last_delta_event_id: "2-0",
  delta_count_last_batch: 12,
  page_polling_enabled: true,
  recommended_poll_interval_seconds: 60,
};

function minuteItem(freq: string, overrides: Partial<OpsRealtimeStockRtMinHealthItem> = {}): OpsRealtimeStockRtMinHealthItem {
  return {
    freq,
    feed_key: `tushare_stock_rt_min_${freq.toLowerCase()}`,
    status: "ok",
    enabled: true,
    redis_connected: true,
    collector_running: true,
    collector_id: `collector-${freq}`,
    last_request_at: "2026-06-01T10:00:00+08:00",
    last_success_at: "2026-06-01T10:00:01+08:00",
    last_error_at: null,
    last_error_message: null,
    current_batch_id: `batch-${freq}`,
    current_batch_age_seconds: 5,
    current_batch_received_at: "2026-06-01T10:00:01+08:00",
    current_batch_published_at: "2026-06-01T10:00:02+08:00",
    snapshot_count: 4800,
    source_row_count: 4810,
    source_elapsed_ms: 180,
    write_elapsed_ms: 40,
    request_count_last_minute: 1,
    max_calls_per_minute: 20,
    poll_interval_seconds: 60,
    is_trading_day: true,
    collection_sessions: ["09:30-11:30", "13:00-15:00"],
    collection_status: "open",
    stale_after_seconds: 90,
    snapshot_ttl_seconds: 259200,
    keep_recent_batches: 3,
    batch_stream_maxlen: 200,
    delta_stream_maxlen: 1000,
    last_batch_event_id: `batch-${freq}-event`,
    last_delta_event_id: `delta-${freq}-event`,
    delta_count_last_batch: 8,
    invalid_count: 0,
    invalid_reason_counts: {},
    ...overrides,
  };
}

const minuteHealth: OpsRealtimeStockRtMinHealthResponse = {
  display_name: "股票实时分钟",
  status: "degraded",
  enabled: true,
  configured_freqs: ["1MIN", "5MIN", "15MIN", "30MIN", "60MIN"],
  supported_freqs: ["1MIN", "5MIN", "15MIN", "30MIN", "60MIN"],
  page_polling_enabled: true,
  recommended_poll_interval_seconds: 60,
  items: [
    minuteItem("1MIN", {
      invalid_count: 3,
      invalid_reason_counts: { freq_mismatch: 2, missing_time: 1 },
    }),
    minuteItem("5MIN", { status: "stale", current_batch_age_seconds: 120 }),
    minuteItem("15MIN", { status: "unavailable", last_error_message: "Redis unavailable" }),
    minuteItem("30MIN", { status: "degraded", last_error_message: "provider degraded" }),
    minuteItem("60MIN", {
      status: "disabled",
      enabled: false,
      collection_status: "disabled",
      collector_running: false,
      current_batch_id: null,
    }),
  ],
};

const etfHealth: OpsRealtimeEtfRtDailyHealthResponse = {
  feed_key: "tushare_etf_rt_k",
  display_name: "ETF 实时日线",
  status: "ok",
  enabled: true,
  redis_connected: true,
  collector_running: true,
  collector_id: "collector-etf",
  last_request_at: "2026-06-18T10:15:00+08:00",
  last_success_at: "2026-06-18T10:15:01+08:00",
  last_error_at: null,
  last_error_message: null,
  current_batch_id: "etf-batch-1",
  current_batch_age_seconds: 4,
  current_batch_received_at: "2026-06-18T10:15:01+08:00",
  current_batch_published_at: "2026-06-18T10:15:02+08:00",
  source_snapshot_count: 3309,
  eligible_etf_count: 1395,
  eligible_snapshot_count: 1320,
  snapshot_count: 3309,
  source_row_count: 3309,
  source_elapsed_ms: 240,
  write_elapsed_ms: 35,
  request_count_last_minute: 2,
  max_calls_per_minute: 10,
  poll_interval_seconds: 60,
  is_trading_day: true,
  collection_sessions: ["09:30-11:30", "13:00-15:00"],
  collection_status: "open",
  stale_after_seconds: 180,
  snapshot_ttl_seconds: 259200,
  keep_recent_batches: 3,
  batch_stream_maxlen: 5000,
  delta_stream_maxlen: 200000,
  last_batch_event_id: "etf-batch-event",
  last_delta_event_id: "etf-delta-event",
  delta_count_last_batch: 88,
  invalid_count: 2,
  invalid_reason_counts: { missing_ts_code: 2 },
  segment_counts: { SH: 1727, SZ: 1582 },
  page_polling_enabled: true,
  recommended_poll_interval_seconds: 60,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <OpsRealtimeMonitorPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("实时流监控页", () => {
  beforeEach(() => {
    apiRequest.mockReset();
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/realtime/stock-rt-daily/health") return dailyHealth;
      if (path === "/api/v1/ops/realtime/stock-rt-min/health") return minuteHealth;
      if (path === "/api/v1/ops/realtime/etf-rt-daily/health") return etfHealth;
      throw new Error(`unexpected api path: ${path}`);
    });
  });

  it("展示股票实时日线、股票实时分钟和 ETF 实时日线", async () => {
    renderPage();

    expect(await screen.findByText("股票实时日线")).toBeInTheDocument();
    expect(await screen.findByText("股票实时分钟")).toBeInTheDocument();
    expect(await screen.findByText("ETF 实时日线")).toBeInTheDocument();
    for (const freq of ["1MIN", "5MIN", "15MIN", "30MIN", "60MIN"]) {
      expect(await screen.findByText(`${freq} 分钟`)).toBeInTheDocument();
    }
    expect(await screen.findByText("1MIN 存在无效行")).toBeInTheDocument();
    expect(await screen.findByText(/freq_mismatch 2 条/)).toBeInTheDocument();
    expect(await screen.findByText("5MIN 刷新滞后")).toBeInTheDocument();
    expect(await screen.findByText("15MIN 暂不可用")).toBeInTheDocument();
    expect(await screen.findByText("provider degraded")).toBeInTheDocument();
    expect(await screen.findByText("ETF 实时日线存在无效行")).toBeInTheDocument();
    expect(await screen.findByText(/SH 1,727 行/)).toBeInTheDocument();
    expect(await screen.findByText("可请求 ETF 覆盖")).toBeInTheDocument();
    expect(await screen.findByText("1,320 / 1,395")).toBeInTheDocument();
    expect(screen.queryByText("活跃池命中")).not.toBeInTheDocument();
    expect((await screen.findAllByText("已停用")).length).toBeGreaterThan(0);
  });

  it("分钟监控读取失败时不影响日线区块展示", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/realtime/stock-rt-daily/health") return dailyHealth;
      if (path === "/api/v1/ops/realtime/stock-rt-min/health") throw new Error("minute health failed");
      if (path === "/api/v1/ops/realtime/etf-rt-daily/health") return etfHealth;
      throw new Error(`unexpected api path: ${path}`);
    });

    renderPage();

    expect(await screen.findByText("股票实时日线")).toBeInTheDocument();
    expect(await screen.findByText("读取股票实时分钟监控失败")).toBeInTheDocument();
    expect(await screen.findByText("minute health failed")).toBeInTheDocument();
  });

  it("ETF 监控读取失败时不影响股票日线和分钟区块展示", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/realtime/stock-rt-daily/health") return dailyHealth;
      if (path === "/api/v1/ops/realtime/stock-rt-min/health") return minuteHealth;
      if (path === "/api/v1/ops/realtime/etf-rt-daily/health") throw new Error("etf health failed");
      throw new Error(`unexpected api path: ${path}`);
    });

    renderPage();

    expect(await screen.findByText("股票实时日线")).toBeInTheDocument();
    expect(await screen.findByText("股票实时分钟")).toBeInTheDocument();
    expect(await screen.findByText("读取 ETF 实时日线监控失败")).toBeInTheDocument();
    expect(await screen.findByText("etf health failed")).toBeInTheDocument();
  });

  it("只调用 Ops health API，不调用业务快照 API，也不给分钟 health 拼 freq", async () => {
    renderPage();

    await screen.findByText("股票实时分钟");
    await waitFor(() => {
      const paths = apiRequest.mock.calls.map(([path]) => String(path));
      expect(paths).toContain("/api/v1/ops/realtime/stock-rt-daily/health");
      expect(paths).toContain("/api/v1/ops/realtime/stock-rt-min/health");
      expect(paths).toContain("/api/v1/ops/realtime/etf-rt-daily/health");
      expect(paths.some((path) => path.startsWith("/api/v1/realtime/stock-rt-min"))).toBe(false);
      expect(paths.some((path) => path.includes("/stock-rt-min/health?freq="))).toBe(false);
    });
  });
});
