import { describe, expect, it } from "vitest";

import { makeTrendPayload } from "../testing/indexDetailTestFixtures";
import { buildTrendChannelViewModel } from "./trendChannelAdapter";

describe("buildTrendChannelViewModel", () => {
  it("parses decimal strings and drops invalid bands without inventing values", () => {
    const payload = makeTrendPayload();
    payload.bars.push({ ...payload.bars[0], trade_date: "20260801", short_channel: { ...payload.bars[0].short_channel, upper: "bad" } });
    const result = buildTrendChannelViewModel(payload);
    expect(result.status).toBe("PARTIAL");
    expect(result.droppedCount).toBe(1);
    expect(result.points[0]).toMatchObject({ time: "2026-07-30", close: 9, shortUpper: 12, shortLower: 10 });
  });
});
