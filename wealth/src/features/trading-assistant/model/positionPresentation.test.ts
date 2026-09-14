import { describe, expect, it } from "vitest";
import type { PositionRow } from "../api/generatedContracts";
import { fixedUnits, positionNumber, positionPercent, sortPositions } from "./positionPresentation";
import { pieSector, positionTiles } from "./positionGeometry";
describe("positions precision and geometry", () => {
  it("keeps all large amount digits and zero signs", () => {
    expect(positionNumber("999999999999999999.99")).toBe("999,999,999,999,999,999.99");
    expect(positionNumber("0.00", true)).toBe("0.00");
    expect(positionPercent("-0.01", true)).toBe("-0.01%");
    expect(positionNumber(null)).toBe("—");
    expect(fixedUnits("-0.01")).toBe(-1n);
  });
  it("sorts exact values, unknowns last in both directions, equal values by stock code", () => {
    const rows = ["9007199254740992.02", null, "9007199254740992.01", "9007199254740992.02"].map((marketValue, i) => ({ stockRef: { tsCode: String(i) }, marketValue } as PositionRow));
    expect(sortPositions(rows, "marketValue").map(row => row.stockRef.tsCode)).toEqual(["0", "3", "2", "1"]);
    expect(sortPositions(rows, "marketValue", false).map(row => row.stockRef.tsCode)).toEqual(["2", "0", "3", "1"]);
    expect(rows[0].stockRef.tsCode).toBe("0");
  });
  it("maps every stock to its area, handles empty/one-stock pies", () => {
    const tiles = positionTiles(Array.from({ length: 11 }, (_, i) => ({ id: String(i), value: BigInt(i + 1) })));
    expect(tiles).toHaveLength(11);
    expect(tiles.reduce((sum, tile) => sum + tile.width * tile.height, 0)).toBeCloseTo(420000, 3);
    for (const tile of tiles) expect(tile.width * tile.height / 420000).toBeCloseTo((Number(tile.id) + 1) / 66, 5);
    expect(positionTiles([])).toEqual([]);
    expect(pieSector(0, Math.PI * 2)).toContain("200 380");
  });
});
