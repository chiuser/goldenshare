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

  it("only recommends monthly_last_day for natural calendar month-end dataset actions", () => {
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
});
