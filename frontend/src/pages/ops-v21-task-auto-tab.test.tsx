import { describe, expect, it } from "vitest";

import {
  buildCronExpression,
  formatScheduleRule,
  parseCronExpression,
  resolveEffectiveCalendarPolicy,
} from "./ops-v21-task-auto-tab";

describe("自动任务日期策略", () => {
  const monthlyCalendarAction = {
    action_type: "dataset_action",
    date_selection_rule: "month_end",
  };
  const monthlyTradingAction = {
    action_type: "dataset_action",
    date_selection_rule: "month_last_trading_day",
  };
  const monthlyWindowAction = {
    action_type: "dataset_action",
    date_selection_rule: "month_window",
  };

  it("recommends monthly calendar policies from dataset date selection rules", () => {
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "monthly",
        selectedAction: monthlyCalendarAction as never,
      }),
    ).toBe("monthly_last_day");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "monthly",
        selectedAction: monthlyTradingAction as never,
      }),
    ).toBe("");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "monthly",
        selectedAction: monthlyWindowAction as never,
      }),
    ).toBe("monthly_window_current_month");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "once",
        repeatMode: "monthly",
        selectedAction: monthlyCalendarAction as never,
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
});
