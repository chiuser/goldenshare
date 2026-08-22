import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { appTheme } from "../app/theme";
import { OpsEtfRealtimeMonitorConfigPage } from "./ops-etf-realtime-monitor-config-page";

const { apiRequest } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({ apiRequest }));

const poolResponse = {
  items: [
    {
      id: 1,
      ts_code: "510300.SH",
      etf_name: "沪深300ETF",
      group_key: "broad_base",
      group_name: "宽基ETF",
      enabled: true,
      display_order: 1,
      note: null,
      has_etf_rule_override: false,
      latest_alert_at: null,
      latest_alert_severity: null,
      created_at: "2026-08-22T09:00:00+08:00",
      updated_at: "2026-08-22T09:00:00+08:00",
    },
  ],
  page: 1,
  page_size: 50,
  total: 1,
};

const rulesResponse = {
  items: [
    {
      id: 2,
      scope_type: "global",
      scope_key: "__GLOBAL__",
      scope_display_name: "全局",
      window_minutes: 1,
      observe_ratio: "2",
      alert_ratio: "3",
      strong_ratio: "5",
      cooldown_minutes: 15,
      feishu_enabled: true,
      enabled: true,
      created_at: "2026-08-22T09:00:00+08:00",
      updated_at: "2026-08-22T09:00:00+08:00",
    },
  ],
  total: 1,
};

const alertsResponse = {
  items: [
    {
      id: 3,
      trade_date: "2026-08-22",
      triggered_at: "2026-08-22T10:00:00+08:00",
      bucket_end_time: "10:00:00",
      window_minutes: 1,
      ts_code: "510300.SH",
      etf_name: "沪深300ETF",
      group_key: "broad_base",
      group_name: "宽基ETF",
      severity: "alert",
      current_amount_yuan: "300000000",
      baseline_amount_yuan: "100000000",
      ratio: "3",
      feishu_status: "skipped",
    },
  ],
  page: 1,
  page_size: 50,
  total: 1,
};

const summaryResponse = {
  monitor_total: 1,
  monitor_enabled: 1,
  observe_count: 0,
  alert_count: 1,
  strong_count: 0,
  feishu_success_count: 0,
  feishu_failed_count: 0,
  latest_archive_date: "2026-08-21",
};

const activeEtfsResponse = {
  items: [
    {
      ts_code: "510500.SH",
      csname: "中证500ETF",
      extname: null,
      cname: null,
      exchange: "SH",
      etf_type: "宽基",
      list_date: "2013-03-29",
      list_status: "L",
      latest_fund_daily_date: "2026-08-21",
      in_monitor_pool: false,
    },
    {
      ts_code: "159915.SZ",
      csname: "创业板ETF",
      extname: null,
      cname: null,
      exchange: "SZ",
      etf_type: "宽基",
      list_date: "2011-12-09",
      list_status: "L",
      latest_fund_daily_date: "2026-08-21",
      in_monitor_pool: false,
    },
  ],
  page: 1,
  page_size: 50,
  total: 2,
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <OpsEtfRealtimeMonitorConfigPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("ETF实时监控配置中心", () => {
  beforeEach(() => {
    const addedActiveEtfCodes = new Set<string>();
    apiRequest.mockReset();
    apiRequest.mockImplementation(async (path: string, options?: { method?: string; body?: { ts_code?: string } }) => {
      if (path === "/api/v1/ops/realtime/etf-monitor/pool" && options?.method === "POST") {
        const tsCode = options.body?.ts_code;
        if (tsCode) addedActiveEtfCodes.add(tsCode);
        return { id: 4, ts_code: tsCode };
      }
      if (path.startsWith("/api/v1/ops/realtime/etf-monitor/pool?")) return poolResponse;
      if (path === "/api/v1/ops/realtime/etf-monitor/rules") return rulesResponse;
      if (path.startsWith("/api/v1/ops/realtime/etf-monitor/alerts?")) return alertsResponse;
      if (path.startsWith("/api/v1/ops/realtime/etf-monitor/summary?")) return summaryResponse;
      if (path.startsWith("/api/v1/ops/realtime/etf-monitor/active-etfs?")) {
        return {
          ...activeEtfsResponse,
          items: activeEtfsResponse.items.map((item) => ({ ...item, in_monitor_pool: addedActiveEtfCodes.has(item.ts_code) })),
        };
      }
      throw new Error(`unexpected api path: ${path}`);
    });
  });

  it("展示监控池、阈值规则和告警记录，并按三个区块读取 API", async () => {
    renderPage();

    expect(await screen.findByText("ETF实时监控配置中心")).toBeInTheDocument();
    expect((await screen.findAllByText("沪深300ETF")).length).toBeGreaterThan(0);
    expect(screen.getByRole("tab", { name: "监控池" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "阈值规则" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "告警记录" })).toBeInTheDocument();
    expect(apiRequest).toHaveBeenCalledWith(expect.stringContaining("/pool?page=1&page_size=50"));
    expect(apiRequest).toHaveBeenCalledWith(expect.stringContaining("/alerts?trade_date="));
    expect(apiRequest).toHaveBeenCalledWith(expect.stringContaining("/summary?trade_date="));
    expect(screen.getByRole("button", { name: "删除" })).toHaveAttribute("data-variant", "light");

    fireEvent.click(screen.getByRole("tab", { name: "阈值规则" }));
    expect(await screen.findByText("observe")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "告警记录" }));
    expect((await screen.findAllByText("alert")).length).toBeGreaterThan(0);
  });

  it("添加监控 ETF 时从活跃池按 50 条分页读取，不直连实时源", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "添加ETF" }));

    expect(await screen.findByText("选择并添加 ETF")).toBeInTheDocument();
    expect(await screen.findByText("510500.SH")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "510500.SH启用监控" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "510500.SH展示排序" })).toBeInTheDocument();
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(expect.stringContaining("/active-etfs?page=1&page_size=50"));
    });
    fireEvent.change(screen.getByRole("textbox", { name: "搜索待添加 ETF" }), { target: { value: "中证500" } });
    await waitFor(() => {
      expect(apiRequest.mock.calls.some(([path]) => {
        const url = new URL(String(path), "http://localhost");
        return url.pathname.endsWith("/active-etfs") && url.searchParams.get("keyword") === "中证500";
      })).toBe(true);
    });
    expect(screen.getByText("中证500", { exact: true }).tagName).toBe("MARK");
    expect(screen.getByRole("row", { name: /中证500ETF 510500\.SH/ })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /^添加$/ })[0]);
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/realtime/etf-monitor/pool", {
        method: "POST",
        body: expect.objectContaining({
          ts_code: "510500.SH",
          group_key: "broad_base",
          enabled: true,
          display_order: 0,
        }),
      });
    });
    expect(await screen.findByRole("button", { name: "已添加" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^添加$/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "添加监控ETF" })).toBeInTheDocument();
    const paths = apiRequest.mock.calls.map(([path]) => String(path));
    expect(paths.some((path) => path.includes("tushare"))).toBe(false);
    expect(paths.some((path) => path.includes("/api/v1/realtime/"))).toBe(false);
  });

  it("单个 API 失败只影响当前区块", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/v1/ops/realtime/etf-monitor/pool?")) throw new Error("pool unavailable");
      if (path === "/api/v1/ops/realtime/etf-monitor/rules") return rulesResponse;
      if (path.startsWith("/api/v1/ops/realtime/etf-monitor/alerts?")) return alertsResponse;
      if (path.startsWith("/api/v1/ops/realtime/etf-monitor/summary?")) return summaryResponse;
      throw new Error(`unexpected api path: ${path}`);
    });
    renderPage();

    expect(await screen.findByText("读取监控池失败")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "阈值规则" }));
    expect(await screen.findByText("observe")).toBeInTheDocument();
  });
});
