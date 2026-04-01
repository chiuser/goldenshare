import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { OpsTodayPage } from "./ops-today-page";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children, ...props }: { to: string; children?: unknown }) => (
    <a href={to} {...props}>
      {children as string | number | null | undefined}
    </a>
  ),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(async () => ({
    today_kpis: {
      business_date: "2026-04-01",
      total_requests: 3,
      completed_requests: 1,
      running_requests: 1,
      failed_requests: 0,
      queued_requests: 1,
      attention_dataset_count: 1,
    },
    kpis: {
      total_executions: 3,
      queued_executions: 1,
      running_executions: 1,
      success_executions: 1,
      failed_executions: 0,
      canceled_executions: 0,
      partial_success_executions: 0,
    },
    freshness_summary: {
      total_datasets: 1,
      fresh_datasets: 0,
      lagging_datasets: 1,
      stale_datasets: 0,
      unknown_datasets: 0,
    },
    lagging_datasets: [
      {
        dataset_key: "daily",
        display_name: "股票日线",
        freshness_status: "lagging",
        lag_days: 1,
        expected_business_date: "2026-04-01",
        latest_business_date: "2026-03-31",
        primary_execution_spec_key: "sync_daily.daily",
      },
    ],
    recent_executions: [],
    recent_failures: [],
  })),
}));

describe("今日运行页", () => {
  it("需要关注的数据应直接跳转到手动同步并带上数据项", async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    render(
      <MantineProvider theme={appTheme}>
        <QueryClientProvider client={queryClient}>
          <OpsTodayPage />
        </QueryClientProvider>
      </MantineProvider>,
    );

    const links = await screen.findAllByRole("link", { name: "去处理" });
    expect(links.some((link) => link.getAttribute("href") === "/app/ops/manual-sync?spec_key=sync_daily.daily&spec_type=job")).toBe(true);
    expect(screen.queryByText("需要优先处理的问题")).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "查看全部任务" })).toBeInTheDocument();
  });
});
