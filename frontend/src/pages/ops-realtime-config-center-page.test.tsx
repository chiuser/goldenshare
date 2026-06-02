import { MantineProvider } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { appTheme } from "../app/theme";
import type {
  RealtimeCollectorRestartResponse,
  RealtimeConfigApplyState,
  RealtimeConfigObjectDetailResponse,
  RealtimeConfigObjectListResponse,
  RealtimeConfigRevisionListResponse,
  RealtimeConfigValidateResponse,
} from "../shared/api/realtime-config-types";
import { ApiError } from "../shared/api/errors";
import { OpsRealtimeConfigCenterPage } from "./ops-realtime-config-center-page";

const { apiRequest, navigateMock } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest,
}));

vi.mock("@tanstack/react-router", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

const pendingApplyState: RealtimeConfigApplyState = {
  status: "pending_restart",
  restart_pending: true,
  published_version: 7,
  applied_version: 6,
  collector_id: "collector-1",
  applied_at: "2026-06-02T10:01:00+08:00",
  process_started_at: "2026-06-02T10:00:00+08:00",
  message: "配置已发布，collector 尚未应用当前版本",
};

const appliedDailyState: RealtimeConfigApplyState = {
  status: "applied",
  restart_pending: false,
  published_version: 3,
  applied_version: 3,
  collector_id: "collector-1",
  applied_at: "2026-06-02T10:01:00+08:00",
  process_started_at: "2026-06-02T10:00:00+08:00",
  message: "collector 已应用当前配置版本",
};

const appliedMinState: RealtimeConfigApplyState = {
  ...pendingApplyState,
  status: "applied",
  restart_pending: false,
  applied_version: 7,
  message: "collector 已应用当前配置版本",
};

const objectsResponse: RealtimeConfigObjectListResponse = {
  items: [
    {
      object_key: "stock_rt_min",
      object_kind: "feed_group",
      display_name: "股票实时分钟",
      enabled: true,
      version: 7,
      requires_collector_restart: true,
      apply_state: pendingApplyState,
    },
    {
      object_key: "stock_rt_daily",
      object_kind: "collector_feed",
      display_name: "股票实时日线",
      enabled: false,
      version: 3,
      requires_collector_restart: true,
      apply_state: appliedDailyState,
    },
  ],
};

const stockRtMinDetail: RealtimeConfigObjectDetailResponse = {
  object_key: "stock_rt_min",
  display_name: "股票实时分钟",
  object_kind: "feed_group",
  mode: "published",
  version: 7,
  requires_collector_restart: true,
  apply_state: pendingApplyState,
  effective_config: {
    enabled: true,
    enabled_freqs: ["1MIN", "5MIN", "15MIN", "30MIN", "60MIN"],
    poll_interval_seconds: 60,
    max_calls_per_minute: 20,
    lease_ttl_seconds: 90,
    stale_after_seconds: 90,
    snapshot_ttl_seconds: 259200,
    keep_recent_batches: 3,
    batch_stream_maxlen: 200,
    delta_stream_maxlen: 1000,
    source_timeout_seconds: 8,
  },
  locked_config: {
    source_api_name: "rt_min",
    exchange: "SSE",
    collection_sessions: ["09:30-11:30", "13:00-15:00"],
    ts_code_pattern: "3*.SZ,6*.SH,0*.SZ,9*.BJ",
    feed_key_pattern: "tushare_stock_rt_min_{freq}",
  },
  fields: [
    { key: "enabled", label: "是否启用", editable: true, control: "switch", value_type: "bool", options: [] },
    {
      key: "enabled_freqs",
      label: "启用频率",
      editable: true,
      control: "checkbox_group",
      value_type: "string_array",
      options: ["1MIN", "5MIN", "15MIN", "30MIN", "60MIN"].map((value) => ({ value, label: value })),
    },
    { key: "poll_interval_seconds", label: "采集间隔", editable: true, control: "number_input", value_type: "int", options: [] },
    { key: "max_calls_per_minute", label: "分钟请求上限", editable: true, control: "number_input", value_type: "int", options: [] },
    { key: "source_timeout_seconds", label: "源站超时", editable: true, control: "number_input", value_type: "int", options: [] },
    { key: "source_api_name", label: "源接口", editable: false, control: "locked_text", value_type: "string", options: [] },
    { key: "ts_code_pattern", label: "请求范围", editable: false, control: "locked_text", value_type: "string", options: [] },
    { key: "feed_key_pattern", label: "Feed key 模式", editable: false, control: "locked_text", value_type: "string", options: [] },
  ],
};

const stockRtDailyDetail: RealtimeConfigObjectDetailResponse = {
  object_key: "stock_rt_daily",
  display_name: "股票实时日线",
  object_kind: "collector_feed",
  mode: "published",
  version: 3,
  requires_collector_restart: true,
  apply_state: appliedDailyState,
  effective_config: {
    enabled: false,
    poll_interval_seconds: 6,
    max_calls_per_minute: 20,
    lease_ttl_seconds: 30,
    stale_after_seconds: 20,
    snapshot_ttl_seconds: 259200,
    keep_recent_batches: 3,
    batch_stream_maxlen: 200,
    delta_stream_maxlen: 1000,
  },
  locked_config: {
    source_api_name: "rt_k",
    exchange: "SSE",
    collection_sessions: ["09:30-11:30", "13:00-15:00"],
    ts_code_pattern: "3*.SZ,6*.SH,0*.SZ,9*.BJ",
    feed_key: "tushare_stock_rt_k",
  },
  fields: [
    { key: "enabled", label: "是否启用", editable: true, control: "switch", value_type: "bool", options: [] },
    { key: "poll_interval_seconds", label: "采集间隔", editable: true, control: "number_input", value_type: "int", options: [] },
    { key: "source_api_name", label: "源接口", editable: false, control: "locked_text", value_type: "string", options: [] },
    { key: "feed_key", label: "Feed key", editable: false, control: "locked_text", value_type: "string", options: [] },
  ],
};

const revisionsResponse: RealtimeConfigRevisionListResponse = {
  total: 1,
  items: [
    {
      id: 11,
      object_type: "realtime_runtime_config",
      object_id: "stock_rt_min",
      action: "published",
      before_json: { enabled_freqs: ["1MIN", "5MIN"] },
      after_json: { enabled_freqs: ["1MIN", "5MIN", "15MIN"] },
      changed_by_username: "admin",
      changed_at: "2026-06-02T10:00:00+08:00",
    },
  ],
};

const validValidationResponse: RealtimeConfigValidateResponse = {
  valid: true,
  errors: [],
  warnings: [{ field: null, message: "发布后需要重启 collector 才会生效" }],
  diff: [
    {
      field: "enabled_freqs",
      before: ["1MIN", "5MIN", "15MIN", "30MIN", "60MIN"],
      after: ["1MIN", "15MIN", "30MIN", "60MIN"],
    },
  ],
  impact: {
    requires_collector_restart: true,
    affected_feeds: ["tushare_stock_rt_min_1min"],
  },
};

const restartResponse: RealtimeCollectorRestartResponse = {
  status: "ok",
  service_name: "goldenshare-realtime-collector.service",
  active: true,
  started_at: "2026-06-02T10:05:00+08:00",
  finished_at: "2026-06-02T10:05:02+08:00",
  message: "collector 已重启，等待 collector 上报已应用配置版本",
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <OpsRealtimeConfigCenterPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

function installDefaultApiMock() {
  apiRequest.mockImplementation(async (path: string, options?: { method?: string; body?: unknown }) => {
    if (path === "/api/v1/ops/realtime/config/objects") return objectsResponse;
    if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min/revisions") return revisionsResponse;
    if (path === "/api/v1/ops/realtime/config/objects/stock_rt_daily/revisions") return { total: 0, items: [] };
    if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min/validate") return validValidationResponse;
    if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min" && options?.method === "PUT") return stockRtMinDetail;
    if (path === "/api/v1/ops/realtime/config/collector/restart") return restartResponse;
    if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min") return stockRtMinDetail;
    if (path === "/api/v1/ops/realtime/config/objects/stock_rt_daily") return stockRtDailyDetail;
    throw new Error(`unexpected api path: ${path}`);
  });
}

describe("实时流配置中心页面", () => {
  beforeEach(() => {
    apiRequest.mockReset();
    navigateMock.mockReset();
    installDefaultApiMock();
  });

  it("进入页面后读取对象列表，默认选中第一个对象并读取详情和修订历史", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "实时流配置中心" })).toBeInTheDocument();
    expect(await screen.findByText("股票实时分钟")).toBeInTheDocument();
    expect(await screen.findByText("配置项明细")).toBeInTheDocument();
    expect(await screen.findByText("修订历史")).toBeInTheDocument();
    expect(await screen.findByText("admin")).toBeInTheDocument();

    await waitFor(() => {
      const paths = apiRequest.mock.calls.map(([path]) => String(path));
      expect(paths).toContain("/api/v1/ops/realtime/config/objects");
      expect(paths).toContain("/api/v1/ops/realtime/config/objects/stock_rt_min");
      expect(paths).toContain("/api/v1/ops/realtime/config/objects/stock_rt_min/revisions");
    });
  });

  it("点击对象后右侧切换到对应配置详情", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("股票实时分钟");
    await user.click(screen.getByText("股票实时日线"));

    expect((await screen.findAllByText("tushare_stock_rt_k")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Feed key")).length).toBeGreaterThan(0);
  });

  it("查看态不展示校验结果和发布影响", async () => {
    renderPage();

    expect(await screen.findByText("当前为查看态")).toBeInTheDocument();
    expect(await screen.findAllByText("待重启生效")).not.toHaveLength(0);
    expect(await screen.findByText("发布版本 v7")).toBeInTheDocument();
    expect(screen.queryByText("草稿差异")).not.toBeInTheDocument();
    expect(screen.queryByText("发布影响")).not.toBeInTheDocument();
    expect(screen.queryByText("需重启")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交发布" })).not.toBeInTheDocument();
  });

  it("点击重启 collector 后调用固定重启 API，并等待 collector 上报已应用状态", async () => {
    const notificationSpy = vi.spyOn(notifications, "show").mockReturnValue("restart-success");
    let restarted = false;
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/realtime/config/objects") {
        return {
          items: objectsResponse.items.map((item) => (
            item.object_key === "stock_rt_min" && restarted ? { ...item, apply_state: appliedMinState } : item
          )),
        } satisfies RealtimeConfigObjectListResponse;
      }
      if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min/revisions") return revisionsResponse;
      if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min") {
        return restarted ? { ...stockRtMinDetail, apply_state: appliedMinState } : stockRtMinDetail;
      }
      if (path === "/api/v1/ops/realtime/config/collector/restart") {
        restarted = true;
        return restartResponse;
      }
      throw new Error(`unexpected api path: ${path}`);
    });
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("配置已发布，collector 尚未应用当前版本")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重启 collector" }));

    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/realtime/config/collector/restart", { method: "POST" });
      expect(notificationSpy).toHaveBeenCalledWith(expect.objectContaining({
        title: "重启命令已执行",
      }));
    });
    expect(await screen.findByText("collector 已应用当前配置版本")).toBeInTheDocument();
    await waitFor(() => {
      const paths = apiRequest.mock.calls.map(([path]) => String(path));
      expect(paths.some((path) => path.includes("/health"))).toBe(false);
      expect(paths.some((path) => path.startsWith("/api/v1/realtime/"))).toBe(false);
      expect(paths.some((path) => path.toLowerCase().includes("tushare"))).toBe(false);
      expect(paths.some((path) => path.toLowerCase().includes("redis"))).toBe(false);
    });
  });

  it("编辑态按后端 fields 渲染 switch、number input、checkbox group 和 locked text", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("股票实时分钟");
    await user.click(screen.getByRole("button", { name: "进入编辑模式" }));

    expect(await screen.findByText("当前为编辑态")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /是否启用/ })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "采集间隔" })).toHaveValue("60");
    expect(screen.getByRole("checkbox", { name: "1MIN" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "60MIN" })).toBeChecked();
    expect(screen.getByText("rt_min")).toBeInTheDocument();
    expect(screen.getByText("tushare_stock_rt_min_{freq}")).toBeInTheDocument();
  });

  it("enabled_freqs 多选变更后调用 validate，展示 diff 和 warnings，校验通过后允许发布", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("股票实时分钟");
    await user.click(screen.getByRole("button", { name: "进入编辑模式" }));
    await user.click(screen.getByRole("checkbox", { name: "5MIN" }));
    await user.click(screen.getByRole("button", { name: "校验草稿" }));

    expect(await screen.findByText("校验通过")).toBeInTheDocument();
    expect(await screen.findByText("发布后需要重启 collector 才会生效")).toBeInTheDocument();
    expect(await screen.findByText("草稿差异")).toBeInTheDocument();
    expect(await screen.findByText("tushare_stock_rt_min_1min")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交发布" })).toBeEnabled();

    await waitFor(() => {
      const validateCall = apiRequest.mock.calls.find(([path]) => path === "/api/v1/ops/realtime/config/objects/stock_rt_min/validate");
      expect(validateCall?.[1]).toMatchObject({
        method: "POST",
        body: {
          runtime_config: expect.objectContaining({
            enabled_freqs: ["1MIN", "15MIN", "30MIN", "60MIN"],
          }),
        },
      });
    });
  });

  it("validate 失败时展示错误，发布按钮不可用", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/realtime/config/objects") return objectsResponse;
      if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min") return stockRtMinDetail;
      if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min/revisions") return revisionsResponse;
      if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min/validate") {
        return {
          valid: false,
          errors: [{ field: "enabled_freqs", code: "empty_freqs", message: "至少选择一个分钟频率" }],
          warnings: [],
          diff: [],
          impact: { requires_collector_restart: true, affected_feeds: [] },
        } satisfies RealtimeConfigValidateResponse;
      }
      throw new Error(`unexpected api path: ${path}`);
    });
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("股票实时分钟");
    await user.click(screen.getByRole("button", { name: "进入编辑模式" }));
    await user.click(screen.getByRole("button", { name: "校验草稿" }));

    expect(await screen.findByText("校验失败")).toBeInTheDocument();
    expect(await screen.findByText("至少选择一个分钟频率")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交发布" })).toBeDisabled();
  });

  it("publish 成功后刷新对象、详情、修订记录并回到查看态", async () => {
    const notificationSpy = vi.spyOn(notifications, "show").mockReturnValue("publish-success");
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("股票实时分钟");
    await user.click(screen.getByRole("button", { name: "进入编辑模式" }));
    await user.click(screen.getByRole("checkbox", { name: "5MIN" }));
    await user.click(screen.getByRole("button", { name: "校验草稿" }));
    await screen.findByText("校验通过");
    await user.click(screen.getByRole("button", { name: "提交发布" }));

    await waitFor(() => {
      expect(notificationSpy).toHaveBeenCalledWith(expect.objectContaining({
        title: "发布成功",
        message: "发布成功，需要重启 collector 生效。",
      }));
    });
    expect(await screen.findByText("当前为查看态")).toBeInTheDocument();
    await waitFor(() => {
      const paths = apiRequest.mock.calls.map(([path]) => String(path));
      expect(paths.filter((path) => path === "/api/v1/ops/realtime/config/objects").length).toBeGreaterThan(1);
      expect(paths.filter((path) => path === "/api/v1/ops/realtime/config/objects/stock_rt_min").length).toBeGreaterThan(1);
      expect(paths.filter((path) => path === "/api/v1/ops/realtime/config/objects/stock_rt_min/revisions").length).toBeGreaterThan(1);
    });
  });

  it("publish 409 时展示版本冲突提示", async () => {
    apiRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
      if (path === "/api/v1/ops/realtime/config/objects") return objectsResponse;
      if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min/revisions") return revisionsResponse;
      if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min/validate") return validValidationResponse;
      if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min" && options?.method === "PUT") {
        throw new ApiError(409, { code: "conflict", message: "实时流配置已被更新，请刷新后重试" });
      }
      if (path === "/api/v1/ops/realtime/config/objects/stock_rt_min") return stockRtMinDetail;
      throw new Error(`unexpected api path: ${path}`);
    });
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("股票实时分钟");
    await user.click(screen.getByRole("button", { name: "进入编辑模式" }));
    await user.click(screen.getByRole("button", { name: "校验草稿" }));
    await screen.findByText("校验通过");
    await user.click(screen.getByRole("button", { name: "提交发布" }));

    expect(await screen.findByText("配置已被更新，请刷新后重试")).toBeInTheDocument();
  });

  it("不调用 health API、业务实时 API、Tushare 或 Redis 相关接口", async () => {
    renderPage();

    await screen.findByText("股票实时分钟");
    await waitFor(() => {
      const paths = apiRequest.mock.calls.map(([path]) => String(path));
      expect(paths.some((path) => path.includes("/health"))).toBe(false);
      expect(paths.some((path) => path.startsWith("/api/v1/realtime/"))).toBe(false);
      expect(paths.some((path) => path.toLowerCase().includes("tushare"))).toBe(false);
      expect(paths.some((path) => path.toLowerCase().includes("redis"))).toBe(false);
    });
  });
});
