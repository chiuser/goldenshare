import { describe, expect, it } from "vitest";

import { buildTrendChannelLines, resolveTrendTone } from "./trendChannelGeometry";

describe("trend channel geometry", () => {
  const points = [
    { time: "2026-07-28", close: 9, shortUpper: 12, shortLower: 10, longUpper: 15, longLower: 8 },
    { time: "2026-07-29", close: 10, shortUpper: 13, shortLower: 10, longUpper: 16, longLower: 11 },
    { time: "2026-07-31", close: 12, shortUpper: 14, shortLower: 11, longUpper: 17, longLower: 12 },
  ];

  it("uses four frozen colors and treats equality as above", () => {
    expect(resolveTrendTone(points[0], "short")).toBe("short-below");
    expect(resolveTrendTone(points[0], "long")).toBe("long-above");
    expect(resolveTrendTone(points[1], "short")).toBe("short-above");
    expect(resolveTrendTone(points[1], "long")).toBe("long-below");
    expect(resolveTrendTone(points[2], "long")).toBe("long-above");
  });

  it("draws daily bands and breaks connections across missing candle days", () => {
    const lines = buildTrendChannelLines(points, ["2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"]);
    const verticals = lines.filter((line) => line.fromTime === line.toTime);
    const connections = lines.filter((line) => line.fromTime !== line.toTime);
    expect(verticals).toHaveLength(6);
    expect(connections).toHaveLength(4);
    expect(connections.every((line) => line.fromTime === "2026-07-28" && line.toTime === "2026-07-29")).toBe(true);
  });
});
