import { describe, expect, it } from "vitest";

import {
  buildSectorPriceVolumeDetailsViewModel,
  buildSectorPriceVolumeMetaViewModel,
  buildSectorPriceVolumeSnapshotViewModel,
  SectorPriceVolumeContractError,
} from "./sectorPriceVolumeAdapter";
import { priceVolumeDetailsPayload, priceVolumeMetaPayload, priceVolumeSnapshotPayload } from "./sectorPriceVolumeTestFixtures";

const snapshotRequest = { market: "CN_A", tradeDate: "2026-08-27", scope: "LEVEL_1", period: 20, hierarchyVersion: "dc-industry-v1" } as const;
const detailsRequest = { ...snapshotRequest, historyRange: 20, sectorCode: "BK1001.DC" } as const;

describe("sectorPriceVolumeAdapter", () => {
  it("accepts the frozen Meta, Snapshot and Details facts without recomputing them", () => {
    const meta = buildSectorPriceVolumeMetaViewModel(priceVolumeMetaPayload());
    const snapshot = buildSectorPriceVolumeSnapshotViewModel(priceVolumeSnapshotPayload(new URL("http://localhost/snapshot?tradeDate=2026-08-27&scope=LEVEL_1&period=20")), snapshotRequest);
    const details = buildSectorPriceVolumeDetailsViewModel(priceVolumeDetailsPayload(new URL("http://localhost/details?tradeDate=2026-08-27&scope=LEVEL_1&period=20&historyRange=20&sectorCode=BK1001.DC")), detailsRequest);

    expect(meta.periods).toEqual([1, 5, 10, 20, 30]);
    expect(snapshot.kind).toBe("ready");
    expect(details.kind).toBe("ready");
    if (snapshot.kind === "ready") {
      expect(snapshot.data.rows[0]?.priceText).toBe("+8.62%");
      expect(snapshot.data.rows[1]?.amountText).toBe("--");
    }
  });

  it("rejects unknown fields, hierarchy drift, fake coordinates and request drift", () => {
    expect(() => buildSectorPriceVolumeMetaViewModel({ ...priceVolumeMetaPayload(), unexpected: true })).toThrow(SectorPriceVolumeContractError);

    const hierarchyDrift = priceVolumeMetaPayload();
    hierarchyDrift.hierarchy.nodes[2]!.parentSectorCode = "BK1002.DC";
    expect(() => buildSectorPriceVolumeMetaViewModel(hierarchyDrift)).toThrow(/根节点/);

    const fakeCoordinate = priceVolumeSnapshotPayload(new URL("http://localhost/snapshot?tradeDate=2026-08-27&scope=LEVEL_1&period=20"));
    fakeCoordinate.snapshot.rows[1]!.state = "NEUTRAL";
    expect(() => buildSectorPriceVolumeSnapshotViewModel(fakeCoordinate, snapshotRequest)).toThrow(/坐标完整性/);

    const wrongDate = priceVolumeSnapshotPayload(new URL("http://localhost/snapshot?tradeDate=2026-08-26&scope=LEVEL_1&period=20"));
    expect(() => buildSectorPriceVolumeSnapshotViewModel(wrongDate, snapshotRequest)).toThrow(/请求不一致/);
  });

  it("rejects unstable default order, non-closing counts and fake history continuity", () => {
    const wrongOrder = priceVolumeSnapshotPayload(new URL("http://localhost/snapshot?tradeDate=2026-08-27&scope=LEVEL_1&period=20"));
    wrongOrder.snapshot.rows.reverse();
    expect(() => buildSectorPriceVolumeSnapshotViewModel(wrongOrder, snapshotRequest)).toThrow(/默认排序/);

    const wrongCount = priceVolumeSnapshotPayload(new URL("http://localhost/snapshot?tradeDate=2026-08-27&scope=LEVEL_1&period=20"));
    wrongCount.snapshot.missingCoordinateCount = 0;
    expect(() => buildSectorPriceVolumeSnapshotViewModel(wrongCount, snapshotRequest)).toThrow(/计数不闭合/);

    const fakeHistory = priceVolumeDetailsPayload(new URL("http://localhost/details?tradeDate=2026-08-27&scope=LEVEL_1&period=20&historyRange=20&sectorCode=BK1001.DC"));
    fakeHistory.details.history[1]!.tradeDate = "2026-08-25";
    expect(() => buildSectorPriceVolumeDetailsViewModel(fakeHistory, detailsRequest)).toThrow(/历史日期槽/);
  });
});
