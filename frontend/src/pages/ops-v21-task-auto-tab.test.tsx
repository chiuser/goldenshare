import { describe, expect, it } from "vitest";

import {
  buildProbeRunQueryPath,
  buildCronExpression,
  capabilitySupportsCalendarPolicy,
  formatProbeRunCount,
  formatScheduleRule,
  defaultProbeConditionForCapability,
  getProbeCondition,
  getProbeConditionOptions,
  getScheduleTimeFieldLabel,
  hasCompleteRequiredProbeFilters,
  hasRequiredVisibleParameters,
  isTriggerModeAllowed,
  parseCronExpression,
  resolveEffectiveCalendarPolicy,
  shouldShowScheduleTimingFields,
} from "./ops-v21-task-auto-tab";

describe("自动任务日期策略", () => {
  const capability = (policy: string, cronRepeatModes: string[]) => ({
    calendar_policy_rules: [
      {
        policy,
        schedule_types: ["cron"],
        cron_repeat_modes: cronRepeatModes,
        explicit_time_input: "forbidden",
        generated_time_mode: policy === "trigger_day_single_range" ? "range" : "point",
      },
    ],
  });

  const monthlyCalendarCapability = capability("monthly_last_day", ["monthly"]);
  const monthlyTradingCapability = capability("monthly_last_trading_day", ["monthly"]);
  const monthlyWindowCapability = capability("monthly_window_current_month", ["monthly"]);
  const annDateRangeCapability = capability("trigger_day_single_range", ["daily", "weekly", "monthly"]);
  const newsCapability = capability("trigger_day_point", ["intraday_interval"]);
  const fundShareCapability = capability("trigger_day_point", ["daily", "weekly", "monthly", "intraday_interval"]);
  const fundPortfolioCapability = {
    calendar_policy_rules: [
      {
        policy: "latest_completed_calendar_quarter",
        schedule_types: ["cron", "once"],
        cron_repeat_modes: ["weekly", "monthly"],
        explicit_time_input: "forbidden",
        generated_time_mode: "point",
      },
    ],
  };
  const noCalendarPolicyCapability = { calendar_policy_rules: [] };

  it("recommends monthly calendar policies from dataset date selection rules", () => {
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "monthly",
        automationCapability: monthlyCalendarCapability as never,
      }),
    ).toBe("monthly_last_day");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "monthly",
        automationCapability: monthlyTradingCapability as never,
      }),
    ).toBe("monthly_last_trading_day");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "monthly",
        automationCapability: monthlyWindowCapability as never,
      }),
    ).toBe("monthly_window_current_month");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "once",
        repeatMode: "monthly",
        automationCapability: monthlyCalendarCapability as never,
      }),
    ).toBe("");
  });

  it("recommends trigger-day single-range policy for ann_date range-only datasets", () => {
    expect(
      capabilitySupportsCalendarPolicy(
        annDateRangeCapability as never,
        "trigger_day_single_range",
        "cron",
        "daily",
      ),
    ).toBe(true);
    expect(
      capabilitySupportsCalendarPolicy(
        noCalendarPolicyCapability as never,
        "trigger_day_single_range",
        "cron",
        "daily",
      ),
    ).toBe(false);
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "daily",
        automationCapability: annDateRangeCapability as never,
      }),
    ).toBe("trigger_day_single_range");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "once",
        repeatMode: "daily",
        automationCapability: annDateRangeCapability as never,
      }),
    ).toBe("");
  });

  it("uses cron only as execution time carrier for monthly_last_day", () => {
    expect(buildCronExpression("monthly", "19:00", [], "1", "monthly_last_day")).toBe("0 19 * * *");
    expect(parseCronExpression("0 19 * * *", "monthly_last_day")).toMatchObject({
      repeatMode: "monthly",
      repeatTime: "19:00",
      repeatMonthDay: "1",
    });
    expect(formatScheduleRule("cron", "0 19 * * *", null, "monthly_last_day")).toBe("每月最后一天 19:00");
  });

  it("uses cron only as execution time carrier for monthly_last_trading_day", () => {
    expect(buildCronExpression("monthly", "19:00", [], "1", "monthly_last_trading_day")).toBe("0 19 * * *");
    expect(parseCronExpression("0 19 * * *", "monthly_last_trading_day")).toMatchObject({
      repeatMode: "monthly",
      repeatTime: "19:00",
      repeatMonthDay: "1",
    });
    expect(formatScheduleRule("cron", "0 19 * * *", null, "monthly_last_trading_day")).toBe("每月最后一个交易日 19:00");
  });

  it("uses cron only as execution time carrier for monthly_window_current_month", () => {
    expect(buildCronExpression("monthly", "19:00", [], "1", "monthly_window_current_month")).toBe("0 19 * * *");
    expect(parseCronExpression("0 19 * * *", "monthly_window_current_month")).toMatchObject({
      repeatMode: "monthly",
      repeatTime: "19:00",
      repeatMonthDay: "1",
    });
    expect(formatScheduleRule("cron", "0 19 * * *", null, "monthly_window_current_month")).toBe(
      "每月最后一天 19:00，维护当月自然月窗口",
    );
  });

  it("keeps trigger_day_single_range on regular cron occurrence and labels trigger-day maintenance", () => {
    expect(buildCronExpression("daily", "19:00", [], "1", "trigger_day_single_range")).toBe("0 19 * * *");
    expect(buildCronExpression("weekly", "19:00", ["1", "5"], "1", "trigger_day_single_range")).toBe("0 19 * * 1,5");
    expect(parseCronExpression("0 19 * * *", "trigger_day_single_range")).toMatchObject({
      repeatMode: "daily",
      repeatTime: "19:00",
    });
    expect(formatScheduleRule("cron", "0 19 * * *", null, "trigger_day_single_range")).toBe("每天 19:00，维护触发日");
  });

  it("uses backend capability rules for news and fund-share trigger-day point schedules", () => {
    expect(capabilitySupportsCalendarPolicy(newsCapability as never, "trigger_day_point", "cron", "intraday_interval")).toBe(true);
    expect(capabilitySupportsCalendarPolicy(newsCapability as never, "trigger_day_point", "cron", "daily")).toBe(false);
    expect(capabilitySupportsCalendarPolicy(fundShareCapability as never, "trigger_day_point", "cron", "daily")).toBe(true);
    expect(capabilitySupportsCalendarPolicy(noCalendarPolicyCapability as never, "trigger_day_point", "cron", "daily")).toBe(false);
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "intraday_interval",
        automationCapability: newsCapability as never,
      }),
    ).toBe("trigger_day_point");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "daily",
        automationCapability: fundShareCapability as never,
      }),
    ).toBe("trigger_day_point");
  });

  it("builds and formats intraday interval cron for trigger_day_point", () => {
    expect(buildCronExpression("intraday_interval", "19:00", [], "1", "trigger_day_point", "3")).toBe("*/3 * * * *");
    expect(parseCronExpression("*/3 * * * *", "trigger_day_point")).toMatchObject({
      repeatMode: "intraday_interval",
      intradayIntervalMinutes: "3",
    });
    expect(formatScheduleRule("cron", "*/3 * * * *", null, "trigger_day_point")).toBe("每 3 分钟，维护触发日");
    expect(() => buildCronExpression("intraday_interval", "19:00", [], "1", "trigger_day_point", "2")).toThrow(
      "日内高频策略最小间隔为 3 分钟。",
    );
  });

  it("uses the backend fund-portfolio contract for weekly, monthly, and once schedules", () => {
    expect(
      capabilitySupportsCalendarPolicy(
        fundPortfolioCapability as never,
        "latest_completed_calendar_quarter",
        "cron",
        "weekly",
      ),
    ).toBe(true);
    expect(
      capabilitySupportsCalendarPolicy(
        fundPortfolioCapability as never,
        "latest_completed_calendar_quarter",
        "cron",
        "daily",
      ),
    ).toBe(false);
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "monthly",
        automationCapability: fundPortfolioCapability as never,
      }),
    ).toBe("latest_completed_calendar_quarter");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "once",
        repeatMode: "daily",
        automationCapability: fundPortfolioCapability as never,
      }),
    ).toBe("latest_completed_calendar_quarter");
    expect(
      formatScheduleRule(
        "cron",
        "0 19 * * 1",
        null,
        "latest_completed_calendar_quarter",
      ),
    ).toBe("每周 周一 19:00，维护最近已完成季度");
    expect(
      formatScheduleRule(
        "once",
        null,
        "2099-01-01T01:00:00Z",
        "latest_completed_calendar_quarter",
      ),
    ).toBe("单次执行：2099-01-01 01:00，维护最近已完成季度");
  });

  const marginDetailCapability = {
    version: 1,
    default_trigger_mode: "probe",
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
  };

  it("derives probe controls from the catalog capability", () => {
    expect(isTriggerModeAllowed(marginDetailCapability as never, "probe")).toBe(true);
    expect(isTriggerModeAllowed(marginDetailCapability as never, "schedule")).toBe(false);
    expect(defaultProbeConditionForCapability(marginDetailCapability as never)).toBe("remote_margin_detail_ready");
    expect(getProbeConditionOptions(marginDetailCapability as never)).toEqual([
      { value: "remote_margin_detail_ready", label: "源站已完整发布融资融券交易明细" },
    ]);
    expect(getProbeCondition(marginDetailCapability as never, "remote_margin_detail_ready")?.probe.source).toBe(
      "system_default",
    );
    expect(formatProbeRunCount(4)).toBe("已探测：4 次");
    expect(formatProbeRunCount(undefined)).toBe("已探测：—");
    expect(buildProbeRunQueryPath({ scheduleId: 12, datasetKey: "margin_detail", limit: 1 })).toBe(
      "/api/v1/ops/probes/runs?schedule_id=12&dataset_key=margin_detail&limit=1",
    );
  });

  it("requires the catalog-declared complete index-minutes frequencies", () => {
    const indexMinsCapability = {
      ...marginDetailCapability,
      probe_conditions: [
        {
          ...marginDetailCapability.probe_conditions[0],
          kind: "remote_index_mins_ready",
          filters: {
            mode: "required_allowed_values",
            required_fields: ["freq"],
            allowed_values: { freq: ["1min", "5min", "15min", "30min", "60min"] },
            require_complete_allowed_values: true,
          },
          probe: {
            ...marginDetailCapability.probe_conditions[0].probe,
          },
        },
      ],
    };
    const condition = getProbeCondition(indexMinsCapability as never, "remote_index_mins_ready");
    expect(hasCompleteRequiredProbeFilters(condition as never, { freq: ["1min", "5min", "15min", "30min", "60min"] })).toBe(true);
    expect(hasCompleteRequiredProbeFilters(condition as never, { freq: ["1min", "5min"] })).toBe(false);
  });

  it("keeps workflow capabilities schedule-only", () => {
    const workflowCapability = {
      version: 1,
      default_trigger_mode: "schedule",
      trigger_options: [{ mode: "schedule", allowed_schedule_types: ["cron", "once"] }],
      probe_conditions: [],
    };
    expect(isTriggerModeAllowed(workflowCapability as never, "schedule")).toBe(true);
    expect(isTriggerModeAllowed(workflowCapability as never, "probe")).toBe(false);
    expect(defaultProbeConditionForCapability(workflowCapability as never)).toBe("");
  });

  it("hides schedule timing fields for pure probe and relabels fallback timing", () => {
    expect(shouldShowScheduleTimingFields("probe")).toBe(false);
    expect(shouldShowScheduleTimingFields("schedule")).toBe(true);
    expect(shouldShowScheduleTimingFields("schedule_probe_fallback")).toBe(true);
    expect(getScheduleTimeFieldLabel("schedule")).toBe("执行时间");
    expect(getScheduleTimeFieldLabel("schedule_probe_fallback")).toBe("兜底执行时间");
  });

  it("opens maintenance parameters when visible required parameters exist", () => {
    expect(hasRequiredVisibleParameters([
      {
        key: "ts_code",
        display_name: "证券代码",
        param_type: "string",
        description: "",
        required: true,
        options: [],
        multi_value: false,
        default_value: null,
      },
    ])).toBe(true);
    expect(hasRequiredVisibleParameters([
      {
        key: "trade_date",
        display_name: "交易日期",
        param_type: "date",
        description: "",
        required: true,
        options: [],
        multi_value: false,
        default_value: null,
      },
      {
        key: "limit",
        display_name: "分页条数",
        param_type: "integer",
        description: "",
        required: true,
        options: [],
        multi_value: false,
        default_value: null,
      },
    ])).toBe(false);
  });
});
