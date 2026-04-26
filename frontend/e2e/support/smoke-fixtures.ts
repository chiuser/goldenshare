import type { Page, Route } from "@playwright/test";

type SmokeScenario =
  | "ops-overview"
  | "task-center"
  | "task-records"
  | "task-manual"
  | "task-auto"
  | "task-detail"
  | "review-index"
  | "review-board"
  | "share-market";

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

function createTaskRunItem(overrides: Record<string, unknown> = {}) {
  return {
    id: 101,
    task_type: "dataset_action",
    resource_key: "daily",
    action: "maintain",
    title: "股票日线",
    time_scope: {
      kind: "point",
      start: "2026-04-17",
      end: "2026-04-17",
      label: "2026-04-17",
    },
    time_scope_label: "2026-04-17",
    schedule_display_name: null,
    trigger_source: "manual",
    status: "running",
    requested_by_username: "admin",
    requested_at: "2026-04-17T09:30:00+08:00",
    started_at: "2026-04-17T09:30:02+08:00",
    ended_at: null,
    unit_total: 120,
    unit_done: 68,
    unit_failed: 0,
    rows_fetched: 5200,
    rows_saved: 5100,
    rows_rejected: 100,
    progress_percent: 57,
    primary_issue_id: null,
    primary_issue_title: null,
    ...overrides,
  };
}

function createTaskRunView(overrides: Record<string, unknown> = {}) {
  const item = createTaskRunItem(overrides);
  const id = Number(item.id);
  return {
    run: {
      id,
      task_type: item.task_type,
      resource_key: item.resource_key,
      action: item.action,
      title: item.title,
      trigger_source: item.trigger_source,
      status: item.status,
      status_reason_code: null,
      requested_by_username: item.requested_by_username,
      schedule_display_name: item.schedule_display_name,
      time_input: {
        mode: "point",
        trade_date: "2026-04-17",
      },
      filters: {},
      time_scope: item.time_scope,
      time_scope_label: item.time_scope_label,
      requested_at: item.requested_at,
      queued_at: "2026-04-17T09:30:01+08:00",
      started_at: item.started_at,
      ended_at: item.ended_at,
      cancel_requested_at: null,
      canceled_at: null,
    },
    progress: {
      unit_total: item.unit_total,
      unit_done: item.unit_done,
      unit_failed: item.unit_failed,
      progress_percent: item.progress_percent,
      rows_fetched: item.rows_fetched,
      rows_saved: item.rows_saved,
      rows_rejected: item.rows_rejected,
      current_context: {
        trade_date: "2026-04-17",
        ts_code: "002034.SZ",
      },
    },
    primary_issue: null,
    nodes: [
      {
        id: id * 10,
        parent_node_id: null,
        node_key: `${item.resource_key}:2026-04-17`,
        node_type: "dataset_plan",
        sequence_no: 1,
        title: `维护 ${item.title}`,
        resource_key: item.resource_key,
        status: item.status,
        time_input: {
          mode: "point",
          trade_date: "2026-04-17",
        },
        context: {},
        rows_fetched: item.rows_fetched,
        rows_saved: item.rows_saved,
        rows_rejected: item.rows_rejected,
        issue_id: null,
        started_at: item.started_at,
        ended_at: item.ended_at,
        duration_ms: null,
      },
    ],
    node_total: 1,
    nodes_truncated: false,
    actions: {
      can_retry: item.status === "failed",
      can_cancel: item.status === "queued" || item.status === "running",
      can_copy_params: true,
    },
  };
}

function mockTradeCalendar(route: Route, pathname: string) {
  if (pathname !== "/api/v1/market/trade-calendar") {
    return null;
  }

  return fulfillJson(route, {
    exchange: "SSE",
    items: [
      { trade_date: "2026-04-13", is_open: true, pretrade_date: "2026-04-10" },
      { trade_date: "2026-04-14", is_open: true, pretrade_date: "2026-04-13" },
      { trade_date: "2026-04-15", is_open: true, pretrade_date: "2026-04-14" },
      { trade_date: "2026-04-16", is_open: true, pretrade_date: "2026-04-15" },
      { trade_date: "2026-04-17", is_open: true, pretrade_date: "2026-04-16" },
      { trade_date: "2026-04-18", is_open: false, pretrade_date: "2026-04-17" },
      { trade_date: "2026-04-19", is_open: false, pretrade_date: "2026-04-17" },
      { trade_date: "2026-04-20", is_open: true, pretrade_date: "2026-04-17" },
      { trade_date: "2026-04-21", is_open: true, pretrade_date: "2026-04-20" },
      { trade_date: "2026-04-22", is_open: true, pretrade_date: "2026-04-21" },
      { trade_date: "2026-04-23", is_open: true, pretrade_date: "2026-04-22" },
      { trade_date: "2026-04-24", is_open: true, pretrade_date: "2026-04-23" },
      { trade_date: "2026-04-25", is_open: false, pretrade_date: "2026-04-24" },
      { trade_date: "2026-04-26", is_open: false, pretrade_date: "2026-04-24" },
      { trade_date: "2026-04-27", is_open: true, pretrade_date: "2026-04-24" },
      { trade_date: "2026-04-28", is_open: true, pretrade_date: "2026-04-27" },
      { trade_date: "2026-04-29", is_open: true, pretrade_date: "2026-04-28" },
      { trade_date: "2026-04-30", is_open: true, pretrade_date: "2026-04-29" },
      { trade_date: "2026-05-01", is_open: false, pretrade_date: "2026-04-30" },
      { trade_date: "2026-05-02", is_open: false, pretrade_date: "2026-04-30" },
      { trade_date: "2026-05-03", is_open: false, pretrade_date: "2026-04-30" },
      { trade_date: "2026-05-04", is_open: true, pretrade_date: "2026-04-30" },
      { trade_date: "2026-05-05", is_open: true, pretrade_date: "2026-05-04" },
      { trade_date: "2026-05-06", is_open: true, pretrade_date: "2026-05-05" },
      { trade_date: "2026-05-07", is_open: true, pretrade_date: "2026-05-06" },
    ],
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
      actions: [
        { key: "daily.maintain", action_type: "dataset_action", display_name: "维护股票日线", target_key: "daily", target_display_name: "股票日线" },
        { key: "moneyflow_ind_dc.maintain", action_type: "dataset_action", display_name: "板块资金流向（东财）", target_key: "moneyflow_ind_dc", target_display_name: "板块资金流向（东财）" },
      ],
      workflows: [],
    });
  }

  if (pathname === "/api/v1/ops/task-runs/summary") {
    return fulfillJson(route, {
      total: 2,
      queued: 0,
      running: 1,
      success: 0,
      failed: 1,
      canceled: 0,
    });
  }

  if (pathname === "/api/v1/ops/task-runs") {
    return fulfillJson(route, {
      total: 2,
      items: [
        createTaskRunItem({
          id: 101,
          status: "running",
        }),
        createTaskRunItem({
          id: 102,
          resource_key: "moneyflow_ind_dc",
          title: "板块资金流向（东财）",
          time_scope_label: "2026-04-17",
          trigger_source: "scheduled",
          status: "failed",
          requested_by_username: "system",
          requested_at: "2026-04-17T08:40:00+08:00",
          started_at: "2026-04-17T08:40:03+08:00",
          ended_at: "2026-04-17T08:41:12+08:00",
          rows_fetched: 0,
          rows_saved: 0,
          rows_rejected: 0,
          unit_total: 0,
          unit_done: 0,
          unit_failed: 1,
          progress_percent: 0,
          primary_issue_id: 1,
          primary_issue_title: "上游接口超时，等待人工重试",
        }),
      ],
    });
  }

  return fulfillJson(route, { detail: `unhandled api: ${pathname}` }, 404);
}

function mockTaskManual(route: Route, pathname: string) {
  if (pathname === "/api/v1/ops/manual-actions/daily/task-runs" && route.request().method() === "POST") {
    return fulfillJson(route, createTaskRunView({
      id: 901,
      status: "queued",
      unit_total: 0,
      unit_done: 0,
      rows_fetched: 0,
      rows_saved: 0,
      rows_rejected: 0,
      progress_percent: 0,
      started_at: null,
    }));
  }

  if (pathname === "/api/v1/ops/task-runs/901/view") {
    return fulfillJson(route, createTaskRunView({
      id: 901,
      status: "queued",
      requested_at: "2026-04-17T10:00:00+08:00",
      started_at: null,
      unit_total: 0,
      unit_done: 0,
      rows_fetched: 0,
      rows_saved: 0,
      rows_rejected: 0,
      progress_percent: 0,
    }));
  }

  if (pathname === "/api/v1/ops/manual-actions") {
    return fulfillJson(route, {
      groups: [
        {
          group_key: "equity_market",
          group_label: "股票行情",
          group_order: 20,
          actions: [
            {
              action_key: "daily.maintain",
              action_type: "dataset_action",
              display_name: "维护股票日线",
              description: "维护股票日线数据。",
              resource_key: "daily",
              resource_display_name: "股票日线",
              date_model: {
                date_axis: "trade_open_day",
                bucket_rule: "every_open_day",
                window_mode: "point_or_range",
                input_shape: "trade_date_or_start_end",
                observed_field: "trade_date",
                audit_applicable: true,
                not_applicable_reason: null,
              },
              time_form: {
                control: "trade_date_or_range",
                default_mode: "point",
                allowed_modes: ["point", "range"],
                selection_rule: "trading_day_only",
                point_label: "只处理一天",
                range_label: "处理一个时间区间",
              },
              filters: [],
              search_keywords: ["daily", "股票日线"],
              action_order: 100,
              route_keys: ["daily.maintain"],
            },
          ],
        },
      ],
    });
  }

  return fulfillJson(route, { detail: `unhandled api: ${pathname}` }, 404);
}

function mockTaskAuto(route: Route, pathname: string) {
  if (pathname === "/api/v1/ops/catalog") {
    return fulfillJson(route, {
      actions: [
        {
          key: "daily.maintain",
          action_type: "dataset_action",
          display_name: "维护股票日线",
          description: "按单个交易日同步股票日线。",
          target_key: "daily",
          target_display_name: "股票日线",
          target_tables: ["core.equity_daily_bar"],
          manual_enabled: true,
          schedule_enabled: true,
          retry_enabled: true,
          schedule_binding_count: 1,
          active_schedule_count: 1,
          parameters: [
            {
              key: "trade_date",
              display_name: "交易日期",
              param_type: "date",
              description: "单个交易日。",
              required: false,
              multi_value: false,
              options: [],
            },
            {
              key: "market",
              display_name: "市场",
              param_type: "enum",
              description: "按市场筛选。",
              required: false,
              multi_value: true,
              options: ["A股"],
            },
          ],
        },
      ],
      workflows: [],
    });
  }

  if (pathname === "/api/v1/ops/schedules") {
    return fulfillJson(route, {
      total: 1,
      items: [
        {
          id: 201,
          spec_key: "daily.maintain",
          spec_display_name: "维护股票日线",
          target_display_name: "股票日线",
          display_name: "股票日线自动同步",
          status: "active",
          schedule_type: "cron",
          trigger_mode: "schedule",
          cron_expr: "0 19 * * 1,2,3,4,5",
          timezone: "Asia/Shanghai",
          next_run_at: "2026-04-20T19:00:00+08:00",
          updated_at: "2026-04-20T10:00:00+08:00",
        },
      ],
    });
  }

  if (pathname === "/api/v1/ops/schedules/201") {
    return fulfillJson(route, {
      id: 201,
      spec_type: "dataset_action",
      spec_key: "daily.maintain",
      spec_display_name: "维护股票日线",
      target_display_name: "股票日线",
      display_name: "股票日线自动同步",
      status: "active",
      schedule_type: "cron",
      trigger_mode: "schedule",
      cron_expr: "0 19 * * 1,2,3,4,5",
      timezone: "Asia/Shanghai",
      calendar_policy: null,
      probe_config: null,
      params_json: { trade_date: "2026-04-17", market: ["A股"] },
      retry_policy_json: {},
      concurrency_policy_json: {},
      next_run_at: "2026-04-20T19:00:00+08:00",
      last_triggered_at: "2026-04-19T19:00:00+08:00",
      created_by_username: "admin",
      updated_by_username: "admin",
      created_at: "2026-04-10T09:00:00+08:00",
      updated_at: "2026-04-20T10:00:00+08:00",
    });
  }

  if (pathname === "/api/v1/ops/schedules/201/revisions") {
    return fulfillJson(route, {
      total: 1,
      items: [
        {
          id: 401,
          action: "updated",
          before_json: null,
          after_json: null,
          changed_by_username: "admin",
          changed_at: "2026-04-20T10:00:00+08:00",
        },
      ],
    });
  }

  if (pathname === "/api/v1/ops/task-runs") {
    return fulfillJson(route, {
      total: 1,
      items: [
        createTaskRunItem({
          id: 301,
          trigger_source: "scheduled",
          status: "success",
          requested_at: "2026-04-19T19:00:00+08:00",
          rows_fetched: 5200,
          rows_saved: 5200,
          rows_rejected: 0,
          unit_total: 1,
          unit_done: 1,
          progress_percent: 100,
        }),
      ],
    });
  }

  if (pathname === "/api/v1/ops/probes") {
    return fulfillJson(route, {
      total: 0,
      items: [],
    });
  }

  if (pathname === "/api/v1/ops/schedules/stream") {
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: "",
    });
  }

  if (pathname === "/api/v1/ops/schedules/preview" && route.request().method() === "POST") {
    return fulfillJson(route, {
      preview_times: [
        "2026-04-20T19:00:00+08:00",
        "2026-04-21T19:00:00+08:00",
        "2026-04-22T19:00:00+08:00",
        "2026-04-23T19:00:00+08:00",
        "2026-04-24T19:00:00+08:00",
      ],
    });
  }

  return fulfillJson(route, { detail: `unhandled api: ${pathname}` }, 404);
}

function mockTaskCenter(route: Route, pathname: string, url: URL) {
  if (pathname === "/api/v1/ops/catalog") {
    return fulfillJson(route, {
      actions: [
        {
          key: "daily.maintain",
          action_type: "dataset_action",
          display_name: "维护股票日线",
          description: "按单个交易日同步股票日线。",
          target_key: "daily",
          target_display_name: "股票日线",
          target_tables: ["core.equity_daily_bar"],
          manual_enabled: true,
          schedule_enabled: true,
          retry_enabled: true,
          schedule_binding_count: 1,
          active_schedule_count: 1,
          parameters: [
            {
              key: "trade_date",
              display_name: "交易日期",
              param_type: "date",
              description: "单个交易日。",
              required: false,
              multi_value: false,
              options: [],
            },
            {
              key: "market",
              display_name: "市场",
              param_type: "enum",
              description: "按市场筛选。",
              required: false,
              multi_value: true,
              options: ["A股"],
            },
          ],
        },
        {
          key: "moneyflow_ind_dc.maintain",
          action_type: "dataset_action",
          display_name: "板块资金流向（东财）",
          description: "按单个交易日同步板块资金流。",
          target_key: "moneyflow_ind_dc",
          target_display_name: "板块资金流向（东财）",
          target_tables: ["core.moneyflow_ind_dc"],
          manual_enabled: true,
          schedule_enabled: true,
          retry_enabled: true,
          schedule_binding_count: 0,
          active_schedule_count: 0,
          parameters: [],
        },
      ],
      workflows: [],
    });
  }

  if (pathname === "/api/v1/ops/task-runs/summary") {
    return fulfillJson(route, {
      total: 2,
      queued: 0,
      running: 1,
      success: 0,
      failed: 1,
      canceled: 0,
    });
  }

  if (pathname === "/api/v1/ops/task-runs") {
    if (url.searchParams.get("schedule_id") === "201") {
      return fulfillJson(route, {
        total: 1,
        items: [
          createTaskRunItem({
            id: 301,
            trigger_source: "scheduled",
            status: "success",
            requested_at: "2026-04-19T19:00:00+08:00",
            rows_fetched: 5200,
            rows_saved: 5200,
            rows_rejected: 0,
            unit_total: 1,
            unit_done: 1,
            progress_percent: 100,
          }),
        ],
      });
    }
    return fulfillJson(route, {
      total: 2,
      items: [
        createTaskRunItem({
          id: 101,
          status: "running",
        }),
        createTaskRunItem({
          id: 102,
          resource_key: "moneyflow_ind_dc",
          title: "板块资金流向（东财）",
          trigger_source: "scheduled",
          status: "failed",
          requested_by_username: "system",
          requested_at: "2026-04-17T08:40:00+08:00",
          started_at: "2026-04-17T08:40:03+08:00",
          ended_at: "2026-04-17T08:41:12+08:00",
          rows_fetched: 0,
          rows_saved: 0,
          rows_rejected: 0,
          unit_total: 0,
          unit_done: 0,
          unit_failed: 1,
          progress_percent: 0,
          primary_issue_id: 1,
          primary_issue_title: "上游接口超时，等待人工重试",
        }),
      ],
    });
  }

  return mockTaskAuto(route, pathname);
}

function mockTaskDetail(route: Route, pathname: string) {
  if (pathname === "/api/v1/ops/task-runs/1/view") {
    return fulfillJson(route, createTaskRunView({
      id: 1,
      time_scope: {
        kind: "range",
        start: "2026-03-23",
        end: "2026-03-30",
        label: "2026-03-23 ~ 2026-03-30",
      },
      time_scope_label: "2026-03-23 ~ 2026-03-30",
      status: "running",
      requested_at: "2026-03-31T01:00:00Z",
      started_at: "2026-03-31T01:00:02Z",
      rows_fetched: 6,
      rows_saved: 6,
      rows_rejected: 0,
      unit_done: 651,
      unit_total: 5814,
      progress_percent: 11,
    }));
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

function mockReviewBoard(route: Route, pathname: string) {
  if (pathname === "/api/v1/ops/review/board/equity-membership") {
    return fulfillJson(route, {
      dc_trade_date: "2026-04-17",
      total: 1,
      page: 1,
      page_size: 30,
      items: [
        {
          ts_code: "600000.SH",
          equity_name: "浦发银行",
          board_count: 2,
          boards: [
            { provider: "dc", board_code: "BK0475", board_name: "银行" },
            { provider: "ths", board_code: "881155", board_name: "银行板块" },
          ],
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

    const tradeCalendar = mockTradeCalendar(route, pathname);
    if (tradeCalendar) {
      return tradeCalendar;
    }

    if (scenario === "ops-overview") {
      return mockOpsOverview(route, pathname);
    }
    if (scenario === "task-center") {
      return mockTaskCenter(route, pathname, url);
    }
    if (scenario === "task-records") {
      return mockTaskRecords(route, pathname);
    }
    if (scenario === "task-manual") {
      return mockTaskManual(route, pathname);
    }
    if (scenario === "task-auto") {
      return mockTaskAuto(route, pathname);
    }
    if (scenario === "task-detail") {
      return mockTaskDetail(route, pathname);
    }
    if (scenario === "review-index") {
      return mockReviewIndex(route, pathname);
    }
    if (scenario === "review-board") {
      return mockReviewBoard(route, pathname);
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
