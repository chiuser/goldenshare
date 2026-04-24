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

  if (pathname === "/api/v1/ops/executions/summary") {
    return fulfillJson(route, {
      total: 2,
      queued: 0,
      running: 1,
      success: 0,
      failed: 1,
      canceled: 0,
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

function mockTaskManual(route: Route, pathname: string) {
  if (pathname === "/api/v1/ops/manual-actions/daily/executions" && route.request().method() === "POST") {
    return fulfillJson(route, {
      id: 901,
    });
  }

  if (pathname === "/api/v1/ops/executions/901") {
    return fulfillJson(route, {
      id: 901,
      schedule_id: null,
      spec_type: "job",
      spec_key: "sync_daily.daily",
      spec_display_name: "股票日线同步",
      schedule_display_name: null,
      trigger_source: "manual",
      status: "queued",
      requested_by_username: "admin",
      requested_at: "2026-04-17T10:00:00+08:00",
      queued_at: "2026-04-17T10:00:02+08:00",
      started_at: null,
      ended_at: null,
      params_json: {
        trade_date: "2026-04-17",
      },
      summary_message: "系统已经收到同步请求，等待排队执行。",
      rows_fetched: 0,
      rows_written: 0,
      progress_current: 0,
      progress_total: 0,
      progress_percent: 0,
      progress_message: null,
      last_progress_at: null,
      cancel_requested_at: null,
      canceled_at: null,
      error_code: null,
      error_message: null,
    });
  }

  if (pathname === "/api/v1/ops/executions/901/steps") {
    return fulfillJson(route, {
      execution_id: 901,
      items: [],
    });
  }

  if (pathname === "/api/v1/ops/executions/901/events") {
    return fulfillJson(route, {
      execution_id: 901,
      items: [],
    });
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
              action_key: "daily",
              action_type: "job",
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
              route_spec_keys: ["sync_daily.daily", "backfill_equity_series.daily", "sync_history.daily"],
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
      job_specs: [
        {
          key: "sync_daily.daily",
          display_name: "日常同步 / daily",
          category: "sync_daily",
          description: "按单个交易日同步股票日线。",
          strategy_type: "incremental_by_date",
          executor_kind: "sync_service",
          target_tables: ["core.equity_daily_bar"],
          supports_manual_run: true,
          supports_schedule: true,
          supports_retry: true,
          schedule_binding_count: 1,
          active_schedule_count: 1,
          supported_params: [
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
      workflow_specs: [],
    });
  }

  if (pathname === "/api/v1/ops/schedules") {
    return fulfillJson(route, {
      total: 1,
      items: [
        {
          id: 201,
          spec_key: "sync_daily.daily",
          spec_display_name: "股票日线同步",
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
      spec_type: "job",
      spec_key: "sync_daily.daily",
      spec_display_name: "股票日线同步",
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

  if (pathname === "/api/v1/ops/executions") {
    return fulfillJson(route, {
      total: 1,
      items: [
        {
          id: 301,
          spec_key: "sync_daily.daily",
          spec_display_name: "股票日线同步",
          trigger_source: "scheduled",
          status: "success",
          requested_at: "2026-04-19T19:00:00+08:00",
          rows_fetched: 5200,
          rows_written: 5200,
          summary_message: "最近一次自动运行已完成。",
        },
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
      job_specs: [
        {
          key: "sync_daily.daily",
          display_name: "日常同步 / daily",
          category: "sync_daily",
          description: "按单个交易日同步股票日线。",
          strategy_type: "incremental_by_date",
          executor_kind: "sync_service",
          target_tables: ["core.equity_daily_bar"],
          supports_manual_run: true,
          supports_schedule: true,
          supports_retry: true,
          schedule_binding_count: 1,
          active_schedule_count: 1,
          supported_params: [
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
          key: "moneyflow_ind_dc",
          display_name: "板块资金流向（东财）",
          category: "sync_daily",
          description: "按单个交易日同步板块资金流。",
          strategy_type: "incremental_by_date",
          executor_kind: "sync_service",
          target_tables: ["core.moneyflow_ind_dc"],
          supports_manual_run: true,
          supports_schedule: true,
          supports_retry: true,
          schedule_binding_count: 0,
          active_schedule_count: 0,
          supported_params: [],
        },
      ],
      workflow_specs: [],
    });
  }

  if (pathname === "/api/v1/ops/executions/summary") {
    return fulfillJson(route, {
      total: 2,
      queued: 0,
      running: 1,
      success: 0,
      failed: 1,
      canceled: 0,
    });
  }

  if (pathname === "/api/v1/ops/executions") {
    if (url.searchParams.get("schedule_id") === "201") {
      return fulfillJson(route, {
        total: 1,
        items: [
          {
            id: 301,
            spec_key: "sync_daily.daily",
            spec_display_name: "股票日线同步",
            trigger_source: "scheduled",
            status: "success",
            requested_at: "2026-04-19T19:00:00+08:00",
            rows_fetched: 5200,
            rows_written: 5200,
            summary_message: "最近一次自动运行已完成。",
          },
        ],
      });
    }
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

  return mockTaskAuto(route, pathname);
}

function mockTaskDetail(route: Route, pathname: string) {
  if (pathname === "/api/v1/ops/executions/1") {
    return fulfillJson(route, {
      id: 1,
      schedule_id: null,
      spec_type: "job",
      spec_key: "backfill_equity_series.daily",
      spec_display_name: "股票日线维护",
      schedule_display_name: null,
      trigger_source: "manual",
      status: "running",
      requested_by_username: "admin",
      requested_at: "2026-03-31T01:00:00Z",
      queued_at: "2026-03-31T01:00:01Z",
      started_at: "2026-03-31T01:00:02Z",
      ended_at: null,
      params_json: {
        start_date: "2026-03-23",
        end_date: "2026-03-30",
      },
      summary_message: null,
      rows_fetched: 0,
      rows_written: 0,
      progress_current: 651,
      progress_total: 5814,
      progress_percent: 11,
      progress_message: "daily: 651/5814 ts_code=002034.SZ fetched=6 written=6",
      last_progress_at: "2026-03-31T01:00:05Z",
      cancel_requested_at: null,
      canceled_at: null,
      error_code: null,
      error_message: null,
    });
  }

  if (pathname === "/api/v1/ops/executions/1/steps") {
    return fulfillJson(route, {
      execution_id: 1,
      items: [
        {
          id: 10,
          step_key: "backfill_equity_series.daily",
          display_name: "股票日线维护",
          sequence_no: 1,
          unit_kind: null,
          unit_value: null,
          status: "running",
          started_at: "2026-03-31T01:00:02Z",
          ended_at: null,
          rows_fetched: 0,
          rows_written: 0,
          message: null,
        },
      ],
    });
  }

  if (pathname === "/api/v1/ops/executions/1/events") {
    return fulfillJson(route, {
      execution_id: 1,
      items: [
        {
          id: 100,
          step_id: 10,
          event_type: "step_progress",
          level: "info",
          message: "正在拉取 2026-03-23 到 2026-03-30 的股票日线数据",
          payload_json: {},
          occurred_at: "2026-03-31T01:00:05Z",
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
