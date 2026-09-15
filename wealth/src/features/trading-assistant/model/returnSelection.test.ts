import { expect, it } from "vitest";
import { curveSelection, returnStart, shiftReturnMonth } from "./returnSelection";

it("uses the server's history for ALL, including an old closed holding", () => {
  expect(returnStart("ALL", "2026-09-15", "2020-01-02")).toBe("2020-01-02");
  expect(returnStart("ALL", "2026-09-15", null)).toBeNull();
  expect(curveSelection("ALL", null, "2020-01-02", "2026-09-15", "DAY", "context")).toEqual({
    accountMode:"ALL", stockMode:"ALL", requestedStartDate:"2020-01-02", requestedEndDate:"2026-09-15",
    granularity:"DAY", readContext:"context" });
});
it("clamps calendar months without treating a month as thirty days", () => {
  expect(shiftReturnMonth("2024-03-31", -1)).toBe("2024-02-29");
  expect(shiftReturnMonth("2026-03-31", -1)).toBe("2026-02-28");
  expect(returnStart("YEAR", "2024-02-29", null)).toBe("2023-02-28");
  expect(returnStart("YEAR_TO_DATE", "2026-09-15", null)).toBe("2026-01-01");
});
