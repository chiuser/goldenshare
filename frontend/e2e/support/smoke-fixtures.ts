import type { Page, Route } from "@playwright/test";

type SmokeScenario =
  | "ops-overview"
  | "task-center"
  | "task-records"
  | "task-manual"
  | "task-manual-sw2021"
  | "task-auto"
  | "task-detail"
  | "task-detail-paged"
  | "review-index"
  | "review-board";

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
  const timeInput =
    overrides.time_input && typeof overrides.time_input === "object"
      ? (overrides.time_input as Record<string, unknown>)
      : {
          mode: "point",
          trade_date: "2026-04-17",
        };
  return {
    run: {
      id,
      task_type: item.task_type,
      resource_key: item.resource_key,
      source_key: "tushare",
      action_key: `${item.resource_key}.maintain`,
      action: item.action,
      title: item.title,
      trigger_source: item.trigger_source,
      trigger_source_label: "手动",
      status: item.status,
      status_reason_code: null,
      requested_by_username: item.requested_by_username,
      schedule_display_name: item.schedule_display_name,
      time_input: timeInput,
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
      rows_deduplicated: 0,
      ingestion_diagnostics: {},
      rejected_reason_counts: {},
      rejected_reasons: [],
      current_object: {
        title: "正在处理：002034.SZ",
        description: "处理范围：2026-04-17",
        fields: [
          { label: "证券代码", value: "002034.SZ" },
          { label: "交易日", value: "2026-04-17" },
        ],
      } as Record<string, unknown> | null,
      period_source_summary: null,
      paged_unit_progress: null as Record<string, unknown> | null,
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
        time_input: timeInput,
        context: {},
        rows_fetched: item.rows_fetched,
        rows_saved: item.rows_saved,
        rows_rejected: item.rows_rejected,
        rows_deduplicated: 0,
        ingestion_diagnostics: {},
        rejected_reason_counts: {},
        rejected_reasons: [],
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

  if (pathname === "/api/v1/ops/dataset-cards") {
    return fulfillJson(route, {
      total: 1,
      groups: [
        {
          domain_key: "equity_market",
          domain_display_name: "股票行情",
          items: [
            {
              card_key: "daily",
              dataset_key: "daily",
              detail_dataset_key: "daily",
              resource_key: "daily",
              display_name: "股票日线",
              domain_key: "equity_market",
              domain_display_name: "股票行情",
              status: "healthy",
              freshness_status: "fresh",
              delivery_mode: "single_source_serving",
              delivery_mode_label: "单源服务",
              delivery_mode_tone: "success",
              layer_plan: "raw->serving",
              freshness_policy: "continuous_open_day",
              raw_table: "raw_tushare.equity_daily_bar",
              raw_table_label: "raw_tushare.equity_daily_bar",
              target_table: "core_serving.equity_daily_bar",
              latest_business_date: "2026-04-17",
              earliest_business_date: "2026-04-01",
              last_sync_date: "2026-04-17",
              latest_success_at: "2026-04-17T09:03:00+08:00",
              expected_business_date: "2026-04-17",
              latest_observed_date: "2026-04-17",
              latest_observed_date_label: "最新业务日期",
              expected_observed_date: "2026-04-17",
              expected_observed_date_label: "应完成业务日期",
              last_success_label: "最近维护成功时间",
              lag_days: 0,
              freshness_note: null,
              primary_action_key: "daily.maintain",
              active_task_run_status: null,
              active_task_run_started_at: null,
              auto_schedule_status: "none",
              auto_schedule_total: 0,
              auto_schedule_active: 0,
              auto_schedule_next_run_at: null,
              probe_total: 0,
              probe_active: 0,
              std_mapping_configured: true,
              std_cleansing_configured: true,
              resolution_policy_configured: true,
            },
          ],
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
  if (
    pathname === "/api/v1/ops/manual-actions/daily.maintain/task-runs" &&
    route.request().method() === "POST"
  ) {
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
                default_mode: "point",
                modes: [
                  {
                    mode: "point",
                    label: "只处理一天",
                    description: "指定单个交易日。",
                    control: "trade_date",
                    selection_rule: "trading_day_only",
                    date_field: "trade_date",
                  },
                  {
                    mode: "range",
                    label: "处理一个时间区间",
                    description: "指定开始和结束交易日。",
                    control: "trade_date_range",
                    selection_rule: "trading_day_only",
                    date_field: "trade_date",
                  },
                ],
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

function mockTaskManualSw2021(route: Route, pathname: string) {
  const actions = [
    {
      action_key: "index_classify.maintain",
      action_type: "dataset_action",
      display_name: "维护申万 SW2021 行业分类",
      description: "刷新申万 SW2021 行业分类完整快照。",
      resource_key: "index_classify",
      resource_display_name: "申万 SW2021 行业分类",
      action_order: 80,
      route_keys: ["index_classify.maintain"],
    },
    {
      action_key: "index_member_all.maintain",
      action_type: "dataset_action",
      display_name: "维护申万 SW2021 行业成员",
      description: "刷新申万 SW2021 当前与历史行业成员全集。",
      resource_key: "index_member_all",
      resource_display_name: "申万 SW2021 行业成员",
      action_order: 90,
      route_keys: ["index_member_all.maintain"],
    },
    {
      action_key: "sw_daily.maintain",
      action_type: "dataset_action",
      display_name: "维护申万 SW2021 行业日行情",
      description: "按开市交易日维护申万 SW2021 行业日行情源事实。",
      resource_key: "sw_daily",
      resource_display_name: "申万 SW2021 行业日行情",
      action_order: 100,
      route_keys: ["sw_daily.maintain"],
    },
  ].map((action) => ({
    ...action,
    date_model:
      action.resource_key === "sw_daily"
        ? {
            date_axis: "trade_open_day",
            bucket_rule: "every_open_day",
            window_mode: "point_or_range",
            input_shape: "trade_date_or_start_end",
            observed_field: "trade_date",
            audit_applicable: true,
            not_applicable_reason: null,
          }
        : {
            date_axis: "none",
            bucket_rule: "not_applicable",
            window_mode: "none",
            input_shape: "none",
            observed_field: null,
            audit_applicable: false,
            not_applicable_reason: "当前快照不按连续业务日期审计。",
          },
    time_form:
      action.resource_key === "sw_daily"
        ? {
            default_mode: "point",
            max_units_per_execution: 60,
            modes: [
              {
                mode: "point",
                label: "只处理一天",
                description: "指定单个交易日。",
                control: "trade_date",
                selection_rule: "trading_day_only",
                date_field: "trade_date",
              },
              {
                mode: "range",
                label: "处理一个时间区间",
                description: "指定开始和结束交易日。",
                control: "trade_date_range",
                selection_rule: "trading_day_only",
                date_field: "trade_date",
              },
            ],
          }
        : {
            default_mode: "none",
            modes: [
              {
                mode: "none",
                label: "按默认策略处理",
                description: "不填写时间条件，按该维护对象默认策略执行。",
                control: "none",
                selection_rule: "none",
                date_field: null,
              },
            ],
          },
    filters: [],
    search_keywords: [action.resource_key, action.resource_display_name],
  }));

  if (pathname === "/api/v1/ops/manual-actions") {
    return fulfillJson(route, {
      groups: [
        {
          group_key: "board_theme",
          group_label: "板块 / 题材",
          group_order: 50,
          actions,
        },
      ],
    });
  }

  const action = actions.find(
    (item) =>
      pathname === `/api/v1/ops/manual-actions/${item.action_key}/task-runs`,
  );
  if (action && route.request().method() === "POST") {
    const taskRunId =
      action.resource_key === "index_classify"
        ? 902
        : action.resource_key === "index_member_all"
          ? 903
          : 904;
    const isDaily = action.resource_key === "sw_daily";
    return fulfillJson(
      route,
      createTaskRunView({
        id: taskRunId,
        resource_key: action.resource_key,
        title: action.resource_display_name,
        status: "queued",
        time_input: isDaily
          ? { mode: "point", trade_date: "2026-04-17" }
          : { mode: "none" },
        time_scope: isDaily
          ? {
              kind: "point",
              start: "2026-04-17",
              end: "2026-04-17",
              label: "2026-04-17",
            }
          : {
              kind: "none",
              start: null,
              end: null,
              label: "当前快照",
            },
        time_scope_label: isDaily ? "2026-04-17" : "当前快照",
        unit_total: 0,
        unit_done: 0,
        rows_fetched: 0,
        rows_saved: 0,
        rows_rejected: 0,
        progress_percent: 0,
        started_at: null,
      }),
    );
  }

  const taskRunId =
    pathname === "/api/v1/ops/task-runs/902/view"
      ? 902
      : pathname === "/api/v1/ops/task-runs/903/view"
        ? 903
        : pathname === "/api/v1/ops/task-runs/904/view"
          ? 904
          : null;
  if (taskRunId !== null) {
    const actionForRun = actions[taskRunId === 902 ? 0 : taskRunId === 903 ? 1 : 2];
    const isDaily = actionForRun.resource_key === "sw_daily";
    return fulfillJson(
      route,
      createTaskRunView({
        id: taskRunId,
        resource_key: actionForRun.resource_key,
        title: actionForRun.resource_display_name,
        status: "queued",
        time_input: isDaily
          ? { mode: "point", trade_date: "2026-04-17" }
          : { mode: "none" },
        time_scope: isDaily
          ? {
              kind: "point",
              start: "2026-04-17",
              end: "2026-04-17",
              label: "2026-04-17",
            }
          : {
              kind: "none",
              start: null,
              end: null,
              label: "当前快照",
            },
        time_scope_label: isDaily ? "2026-04-17" : "当前快照",
        unit_total: 0,
        unit_done: 0,
        rows_fetched: 0,
        rows_saved: 0,
        rows_rejected: 0,
        progress_percent: 0,
        started_at: null,
      }),
    );
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
          automation_capability: {
            version: 1,
            default_trigger_mode: "schedule",
            calendar_policy_rules: [],
            repeat_policy: null,
            trigger_options: [
              { mode: "schedule", allowed_schedule_types: ["cron", "once"] },
              { mode: "probe", allowed_schedule_types: ["cron", "once"] },
              { mode: "schedule_probe_fallback", allowed_schedule_types: ["cron", "once"] },
            ],
            probe_conditions: [
              {
                kind: "freshness_latest_open",
                label: "最新业务日命中最新交易日",
                description: "最新业务日达到最新开市交易日后创建维护任务。",
                allowed_trigger_modes: ["probe", "schedule_probe_fallback"],
                calendar_policy: "dataset_default",
                time_input: "dataset_default",
                filters: {
                  mode: "dataset_default",
                  required_fields: [],
                  allowed_values: {},
                  require_complete_allowed_values: false,
                },
                probe: {
                  source: "system_default",
                  source_label: "系统默认来源",
                  window: { mode: "operator_default", start: null, end: null },
                  probe_interval_seconds: { mode: "operator_default", value: null },
                  max_triggers_per_day: { mode: "operator_default", value: null },
                },
              },
            ],
          },
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
          key: "margin_detail.maintain",
          action_type: "dataset_action",
          display_name: "维护融资融券交易明细",
          description: "按交易日同步融资融券交易明细。",
          target_key: "margin_detail",
          target_display_name: "融资融券交易明细",
          target_tables: ["core_serving.margin_detail"],
          group_label: "融资融券",
          manual_enabled: true,
          schedule_enabled: true,
          automation_capability: {
            version: 1,
            default_trigger_mode: "probe",
            calendar_policy_rules: [],
            repeat_policy: null,
            trigger_options: [{ mode: "probe", allowed_schedule_types: ["cron", "once"] }],
            probe_conditions: [
              {
                kind: "remote_margin_detail_ready",
                label: "源站已完整发布融资融券交易明细",
                description: "确认三个市场代表证券均已返回上一开市日数据后，创建全市场单日维护任务。",
                allowed_trigger_modes: ["probe"],
                calendar_policy: "forbidden",
                time_input: "forbidden",
                filters: {
                  mode: "forbidden",
                  required_fields: [],
                  allowed_values: {},
                  require_complete_allowed_values: false,
                },
                probe: {
                  source: "system_default",
                  source_label: "系统默认来源",
                  window: { mode: "fixed", start: "09:00", end: "09:30" },
                  probe_interval_seconds: { mode: "fixed", value: 300 },
                  max_triggers_per_day: { mode: "fixed", value: 1 },
                },
              },
            ],
          },
          retry_enabled: true,
          schedule_binding_count: 0,
          active_schedule_count: 0,
          parameters: [
            {
              key: "ts_code",
              display_name: "证券代码",
              param_type: "string",
              description: "仅用于手动补录单只证券。",
              required: false,
              multi_value: false,
              options: [],
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
          target_type: "dataset_action",
          target_key: "daily.maintain",
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
      target_type: "dataset_action",
      target_key: "daily.maintain",
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

function createPagedUnitResult(overrides: Record<string, unknown> = {}) {
  return {
    unit_id: "fund_portfolio:20250331",
    unit_index: 1,
    time: { field: "end_date", point: "2025-03-31" },
    page_count: 70,
    retry_count: 0,
    terminal_page_rows: 730,
    observed_short_page: true,
    rows_fetched: 138730,
    rows_normalized_before_dedupe: 138730,
    rows_staged_unique: 138730,
    rows_deduplicated: 0,
    rows_rejected: 0,
    rows_inserted_new: 138730,
    rows_matched_existing: 0,
    rows_committed: 138730,
    final_scope_count: 138730,
    ...overrides,
  };
}

function mockPagedTaskDetail(route: Route, pathname: string, requestCount: number) {
  if (pathname !== "/api/v1/ops/task-runs/1/view") {
    return fulfillJson(route, { detail: `unhandled api: ${pathname}` }, 404);
  }
  const completedFirstQuarter = createPagedUnitResult();
  const view = createTaskRunView({
    id: 1,
    resource_key: "fund_portfolio",
    title: "公募基金持仓",
    status: requestCount >= 4 ? "success" : "running",
    time_scope: {
      kind: "range",
      start: "2025-03-31",
      end: "2025-06-30",
      label: "2025-03-31 ~ 2025-06-30",
    },
    time_scope_label: "2025-03-31 ~ 2025-06-30",
    unit_total: 2,
    unit_done: requestCount >= 4 ? 2 : 1,
    progress_percent: requestCount >= 4 ? 100 : 50,
    rows_saved: requestCount >= 4 ? 142000 : 138730,
    rows_fetched: requestCount === 1 ? 138730 : requestCount === 2 ? 140730 : 142000,
    rows_rejected: 0,
  });
  const activeBase = {
    unit_id: "fund_portfolio:20250630",
    unit_index: 2,
    unit_total: 2,
    time: { field: "end_date", point: "2025-06-30" },
    page_limit: 2000,
    unit_rows_normalized_before_dedupe: 0,
    unit_rows_staged_unique: 0,
    unit_rows_deduplicated: 0,
    unit_rows_rejected: 0,
    retry_count: 0,
    observed_short_page: false,
    terminal_page_rows: null,
  };
  if (requestCount === 1) {
    view.progress.paged_unit_progress = {
      active: {
        ...activeBase,
        phase: "processing_page",
        current_page_number: 1,
        completed_page_count: 0,
        unit_rows_fetched: 0,
      },
      completed: [completedFirstQuarter],
      completed_truncated: false,
    };
  } else if (requestCount === 2) {
    view.progress.paged_unit_progress = {
      active: {
        ...activeBase,
        phase: "processing_page",
        current_page_number: 2,
        completed_page_count: 1,
        unit_rows_fetched: 2000,
        unit_rows_normalized_before_dedupe: 2000,
        unit_rows_staged_unique: 2000,
      },
      completed: [completedFirstQuarter],
      completed_truncated: false,
    };
  } else if (requestCount === 3) {
    view.progress.paged_unit_progress = {
      active: {
        ...activeBase,
        phase: "publishing",
        current_page_number: 2,
        completed_page_count: 2,
        unit_rows_fetched: 3270,
        unit_rows_normalized_before_dedupe: 3270,
        unit_rows_staged_unique: 3270,
        observed_short_page: true,
        terminal_page_rows: 1270,
      },
      completed: [completedFirstQuarter],
      completed_truncated: false,
    };
  } else {
    view.progress.current_object = null;
    view.progress.paged_unit_progress = {
      active: null,
      completed: [
        completedFirstQuarter,
        createPagedUnitResult({
          unit_id: "fund_portfolio:20250630",
          unit_index: 2,
          time: { field: "end_date", point: "2025-06-30" },
          page_count: 2,
          terminal_page_rows: 1270,
          rows_fetched: 3270,
          rows_normalized_before_dedupe: 3270,
          rows_staged_unique: 3270,
          rows_inserted_new: 3270,
          rows_committed: 3270,
          final_scope_count: 3270,
        }),
      ],
      completed_truncated: false,
    };
  }
  return fulfillJson(route, view);
}

function mockReviewIndex(route: Route, pathname: string) {
  if (pathname === "/api/v1/ops/review/index/active/summary") {
    return fulfillJson(route, {
      active_count: 2,
      daily_available_count: 2,
      weekly_available_count: 2,
      monthly_available_count: 2,
      pending_count: 0,
    });
  }

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
          market: "SSE",
          publisher: "中证指数",
          data_status: "complete",
          missing_layers: [],
          latest_daily_date: "2026-04-17",
          latest_weekly_date: "2026-04-17",
          latest_monthly_date: "2026-04-17",
          first_seen_date: "2026-01-02",
          last_seen_date: "2026-04-17",
          last_checked_at: "2026-04-17T09:10:00+08:00",
        },
        {
          resource: "index_daily",
          ts_code: "000905.SH",
          index_name: "中证500",
          market: "SSE",
          publisher: "中证指数",
          data_status: "complete",
          missing_layers: [],
          latest_daily_date: "2026-04-17",
          latest_weekly_date: "2026-04-17",
          latest_monthly_date: "2026-04-17",
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

export async function installApiMocks(page: Page, scenario: SmokeScenario) {
  let pagedTaskDetailRequestCount = 0;
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
    if (scenario === "task-manual-sw2021") {
      return mockTaskManualSw2021(route, pathname);
    }
    if (scenario === "task-auto") {
      return mockTaskAuto(route, pathname);
    }
    if (scenario === "task-detail") {
      return mockTaskDetail(route, pathname);
    }
    if (scenario === "task-detail-paged") {
      pagedTaskDetailRequestCount += 1;
      return mockPagedTaskDetail(route, pathname, pagedTaskDetailRequestCount);
    }
    if (scenario === "review-index") {
      return mockReviewIndex(route, pathname);
    }
    if (scenario === "review-board") {
      return mockReviewBoard(route, pathname);
    }
    return fulfillJson(route, { detail: `unhandled api: ${pathname}` }, 404);
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
