import { describe, expect, it } from "vitest";

import type { OpsAutomationCapability } from "./api/types";
import {
  filterNonTimeParams,
  getTimeModeLabels,
  hasDeclaredRangeParameters,
  inferTimeCapability,
  resolvePointTimeParameter,
  resolveRangeTimeFields,
} from "./ops-time-capability";

describe("ops-time-capability", () => {
  it("识别日级单点+区间能力", () => {
    const capability = inferTimeCapability([
      { key: "trade_date", display_name: "", param_type: "date", description: "", required: false, options: [], multi_value: false, default_value: null },
      { key: "start_date", display_name: "", param_type: "date", description: "", required: false, options: [], multi_value: false, default_value: null },
      { key: "end_date", display_name: "", param_type: "date", description: "", required: false, options: [], multi_value: false, default_value: null },
      { key: "market", display_name: "", param_type: "enum", description: "", required: false, options: [], multi_value: true, default_value: null },
    ]);

    expect(capability.hasTimeInput).toBe(true);
    expect(capability.supportsPoint).toBe(true);
    expect(capability.supportsRange).toBe(true);
    expect(capability.pointGranularity).toBe("day");
    expect(capability.rangeGranularity).toBe("day");
    expect(getTimeModeLabels(capability)).toEqual({
      point: "只处理一天",
      range: "处理一个时间区间",
    });
  });

  it("识别月级单点+区间能力", () => {
    const capability = inferTimeCapability([
      { key: "month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false, default_value: null },
      { key: "start_month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false, default_value: null },
      { key: "end_month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false, default_value: null },
    ]);

    expect(capability.hasTimeInput).toBe(true);
    expect(capability.supportsPoint).toBe(true);
    expect(capability.supportsRange).toBe(true);
    expect(capability.pointGranularity).toBe("month");
    expect(capability.rangeGranularity).toBe("month");
    expect(getTimeModeLabels(capability)).toEqual({
      point: "只处理一个月",
      range: "处理一个月份区间",
    });
  });

  it("识别公告日期单点能力", () => {
    const capability = inferTimeCapability([
      { key: "ann_date", display_name: "", param_type: "date", description: "", required: false, options: [], multi_value: false, default_value: null },
      { key: "start_date", display_name: "", param_type: "date", description: "", required: false, options: [], multi_value: false, default_value: null },
      { key: "end_date", display_name: "", param_type: "date", description: "", required: false, options: [], multi_value: false, default_value: null },
    ]);

    expect(capability.pointKey).toBe("ann_date");
    expect(capability.pointGranularity).toBe("day");
  });

  it("过滤掉时间参数，只保留其他输入条件", () => {
    const filtered = filterNonTimeParams([
      { key: "month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false, default_value: null },
      { key: "start_month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false, default_value: null },
      { key: "end_month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false, default_value: null },
      { key: "market", display_name: "", param_type: "enum", description: "", required: false, options: ["A"], multi_value: true, default_value: null },
    ]);
    expect(filtered.map((item) => item.key)).toEqual(["market"]);
  });

  it("自动任务严格按 API contract 选择公告日期字段", () => {
    const capability = {
      time_input_contract: {
        supported_modes: ["point", "range"],
        point_field: "ann_date",
        range_start_field: "start_date",
        range_end_field: "end_date",
        granularity: "day",
      },
    } as OpsAutomationCapability;
    const parameters = [{ key: "ann_date" }, { key: "start_date" }, { key: "end_date" }];

    expect(resolvePointTimeParameter(capability, parameters)?.key).toBe("ann_date");
    expect(resolveRangeTimeFields(capability)).toEqual({ start: "start_date", end: "end_date" });
    expect(hasDeclaredRangeParameters(capability, parameters)).toBe(true);
  });
});
