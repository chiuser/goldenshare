import { describe, expect, it } from "vitest";
import { adaptForecast } from "../xxm-forecast/adapter";
import { forecastDebugFixture, forecastReactivationFixture } from "../xxm-forecast/forecastFixtures.test-support";
import type { ForecastPeriod, ForecastDisplayRange } from "../xxm-forecast/types";
import { decodeForecastDebug } from "./forecastDebugContract";

// LLD 5.4/6.6/21.13: literal integer expectations, independently counted.
// The first range is the bounded diagnostic from the real 2026-10-27 response.
const validRanges: Array<{ name: string; value: ForecastDisplayRange }> = [
  { name: "upper=null from the actual failure", value: { lower: 3779.307688860061, upper: null, lowerInclusive: true, upperInclusive: false, displayLower: 3780, displayUpper: null } },
  { name: "unbounded closed integer lower", value: { lower: 4000, upper: null, lowerInclusive: true, upperInclusive: false, displayLower: 4000, displayUpper: null } },
  { name: "unbounded open integer lower", value: { lower: 4000, upper: null, lowerInclusive: false, upperInclusive: false, displayLower: 4001, displayUpper: null } },
  { name: "unbounded open fractional lower", value: { lower: 4000.2, upper: null, lowerInclusive: false, upperInclusive: false, displayLower: 4001, displayUpper: null } },
  { name: "finite closed integers", value: { lower: 2, upper: 175, lowerInclusive: true, upperInclusive: true, displayLower: 2, displayUpper: 175 } },
  { name: "finite open integers", value: { lower: 2, upper: 175, lowerInclusive: false, upperInclusive: false, displayLower: 3, displayUpper: 174 } },
  { name: "finite fractional boundaries", value: { lower: 2.2, upper: 175.8, lowerInclusive: false, upperInclusive: false, displayLower: 3, displayUpper: 175 } },
  { name: "nonempty range with no integer", value: { lower: 2.2, upper: 2.8, lowerInclusive: true, upperInclusive: true, displayLower: null, displayUpper: null } },
  { name: "closed integer point", value: { lower: 3, upper: 3, lowerInclusive: true, upperInclusive: true, displayLower: 3, displayUpper: 3 } },
  { name: "excluded zero", value: { lower: 0, upper: 2, lowerInclusive: false, upperInclusive: true, displayLower: 1, displayUpper: 2 } },
];
const invalidRanges = [
  { name: "unbounded range with finite displayed upper", value: { lower: 4000, upper: null, lowerInclusive: true, upperInclusive: false, displayLower: 4000, displayUpper: -1 } },
  { name: "unbounded range incorrectly declared without integers", value: { lower: 4000, upper: null, lowerInclusive: true, upperInclusive: false, displayLower: null, displayUpper: null } },
  { name: "inclusive infinity", value: { lower: 4000, upper: null, lowerInclusive: true, upperInclusive: true, displayLower: 4000, displayUpper: null } },
  { name: "excluded lower integer displayed", value: { lower: 4000, upper: 4003, lowerInclusive: false, upperInclusive: true, displayLower: 4000, displayUpper: 4003 } },
  { name: "excluded upper integer displayed", value: { lower: 4000, upper: 4003, lowerInclusive: true, upperInclusive: false, displayLower: 4000, displayUpper: 4003 } },
  { name: "finite range incorrectly declared without integers", value: { lower: 2, upper: 175, lowerInclusive: true, upperInclusive: true, displayLower: null, displayUpper: null } },
  { name: "numbers supplied for range with no integer", value: { lower: 2.2, upper: 2.8, lowerInclusive: true, upperInclusive: true, displayLower: 3, displayUpper: 2 } },
  { name: "missing displayed upper", value: { lower: 4000, upper: null, lowerInclusive: true, upperInclusive: false, displayLower: 4000 } },
];

function fixture(period: ForecastPeriod, path: "conditions" | "structureFollowConditions", value: unknown) {
  const response = forecastDebugFixture("399001.SZ", period);
  if (path === "conditions") {
    response.debug.conditions[0]!.priceRanges = [value as ForecastDisplayRange];
  } else {
    const predicates = response.debug.conditions[0]!.predicates;
    const stamp = (day: string) => period === "day" ? day : `${day}T15:00:00+08:00`;
    response.debug.conditions = [];
    response.debug.selectedReference = null;
    response.debug.nearestDecision = { status: "NOT_EVALUATED", reason: null };
    response.debug.structureFollowConditions = [{
      id: "d".repeat(64), outcome: "SIGNAL_DISAPPEARED", relatedStructureId: "old-bottom-structure", direction: "BOTTOM",
      originWave: { sign: -1, start: stamp("2023-01-03"), end: stamp("2023-01-04"), count: 2, price: 100, dif: -60, priceAt: stamp("2023-01-03"), difAt: stamp("2023-01-04") },
      nextSameColorStart: null, nextSameColorCount: 0,
      priceRanges: [value as ForecastDisplayRange], precisionRanges: [], predicates,
    }];
  }
  return response;
}

for (const period of ["day", "m30", "m60", "m90", "m120"] as const) {
  for (const path of ["conditions", "structureFollowConditions"] as const) {
    describe(`${period} ${path} display integers`, () => {
      const options = { tsCode: "399001.SZ", period, debug: 1 as const, decodeDebug: decodeForecastDebug, check: () => {} };
      // All 18 shapes on day; minutes check both entry paths without repeating the matrix.
      it.each(period === "day" ? validRanges : validRanges.slice(0, 1))("accepts $name", ({ value }) => {
        const input = fixture(period, path, value);
        const before = structuredClone(input);
        expect(() => adaptForecast(input, options)).not.toThrow();
        expect(input).toEqual(before);
      });
      it.each(period === "day" ? invalidRanges : invalidRanges.slice(0, 1))("rejects $name", ({ value }) => {
        expect(() => adaptForecast(fixture(period, path, value), options)).toThrow("顶底识别数据与合同不一致");
      });
    });
  }
}

it("accepts disjoint direct and far reactivation ranges with a near main reference", () => {
  const options = { tsCode: "399001.SZ", period: "m90" as const, debug: 1 as const,
    decodeDebug: decodeForecastDebug, check: () => {} };
  const response = forecastReactivationFixture();
  expect(adaptForecast(response, options)).toEqual(response);
  const wrongRole = structuredClone(response);
  wrongRole.debug.conditions[1]!.referenceRole = "NEAR";
  expect(() => adaptForecast(wrongRole, options)).toThrow();
  const noFar = structuredClone(response);
  noFar.debug.farEvaluated = false;
  expect(() => adaptForecast(noFar, options)).toThrow();
  const overlap = structuredClone(response);
  const farRange = overlap.debug.conditions[1]!.priceRanges[0]!;
  farRange.upperInclusive = true;
  farRange.displayUpper = 90;
  expect(() => adaptForecast(overlap, options)).toThrow();
});
