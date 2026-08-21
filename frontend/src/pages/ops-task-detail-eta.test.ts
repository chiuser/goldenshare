import { describe, expect, it } from "vitest";

import { calculateEtaEstimate } from "./ops-task-detail-eta";

function sample(overrides: Partial<Parameters<typeof calculateEtaEstimate>[0]> = {}) {
  return {
    nodeId: 10,
    unitDone: 200,
    unitTotal: 1000,
    monotonicMs: 20_000,
    wallClockMs: 1_700_000_000_000,
    ...overrides,
  };
}

describe("任务详情 Unit ETA", () => {
  it("第一次采样只进入计算中", () => {
    expect(calculateEtaEstimate(sample(), null)).toEqual({ status: "warming_up" });
  });

  it("使用前后两次采样计算剩余时间", () => {
    const result = calculateEtaEstimate(
      sample({ unitDone: 200, monotonicMs: 20_000 }),
      sample({ unitDone: 195, monotonicMs: 10_000 }),
    );

    expect(result.status).toBe("ready");
    if (result.status === "ready") {
      expect(result.etaSeconds).toBe(1_600);
    }
  });

  it("没有完成新 unit 时不估算", () => {
    expect(
      calculateEtaEstimate(
        sample({ unitDone: 200, monotonicMs: 20_000 }),
        sample({ unitDone: 200, monotonicMs: 10_000 }),
      ),
    ).toEqual({ status: "unavailable" });
  });

  it("unit 总数或节点变化时重新预热", () => {
    expect(
      calculateEtaEstimate(
        sample({ unitDone: 2, unitTotal: 20, monotonicMs: 20_000 }),
        sample({ unitDone: 1, unitTotal: 10, monotonicMs: 10_000 }),
      ),
    ).toEqual({ status: "warming_up" });
  });

  it("全部完成时不再显示未来时间", () => {
    expect(calculateEtaEstimate(sample({ unitDone: 1000 }), sample({ unitDone: 995 }))).toEqual({
      status: "completed",
    });
  });
});
