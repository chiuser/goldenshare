import { describe, expect, it } from "vitest";

import { filterNonTimeParams, getTimeModeLabels, inferTimeCapability } from "./ops-time-capability";

describe("ops-time-capability", () => {
  it("识别日级单点+区间能力", () => {
    const capability = inferTimeCapability([
      { key: "trade_date", display_name: "", param_type: "date", description: "", required: false, options: [], multi_value: false },
      { key: "start_date", display_name: "", param_type: "date", description: "", required: false, options: [], multi_value: false },
      { key: "end_date", display_name: "", param_type: "date", description: "", required: false, options: [], multi_value: false },
      { key: "market", display_name: "", param_type: "enum", description: "", required: false, options: [], multi_value: true },
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
      { key: "month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false },
      { key: "start_month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false },
      { key: "end_month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false },
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

  it("过滤掉时间参数，只保留其他输入条件", () => {
    const filtered = filterNonTimeParams([
      { key: "month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false },
      { key: "start_month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false },
      { key: "end_month", display_name: "", param_type: "month", description: "", required: false, options: [], multi_value: false },
      { key: "market", display_name: "", param_type: "enum", description: "", required: false, options: ["A"], multi_value: true },
    ]);
    expect(filtered.map((item) => item.key)).toEqual(["market"]);
  });
});
