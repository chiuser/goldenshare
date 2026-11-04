import { expect, it } from "vitest";
import { resolveIndexRecognitionAvailability as resolve } from "./indexRecognitionAvailability";

// Expansion scope: the existing homepage indices except BSE 50.
const codes = ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH", "000300.SH",
  "000905.SH", "000852.SH", "000510.SH", "000016.SH"];

it.each(codes)("uses the validated current page identity and exact debug parameter for %s", tsCode => {
  for (const development of [true, false]) {
    for (const search of ["", "?debug=0", "?debug=1", "?debug=true", "?debug=01"]) {
      const value = resolve({ development, tsCode, validatedTsCode: tsCode, search });
      expect(value.recognitionEnabled).toBe(development);
      expect(value.debugEnabled).toBe(development && search === "?debug=1");
    }
  }
});

it.each(codes)("does not enable recognition for unvalidated or previous-index data: %s", tsCode => {
  const otherCode = tsCode === "000001.SH" ? "399001.SZ" : "000001.SH";
  for (const validatedTsCode of [null, otherCode]) {
    expect(resolve({ development: true, tsCode, validatedTsCode, search: "?debug=1" }))
      .toEqual({ recognitionEnabled: false, debugEnabled: false });
  }
});

it("keeps BSE recognition disabled even with a validated page", () => {
  for (const development of [true, false]) {
    expect(resolve({ development, tsCode: "899050.BJ", validatedTsCode: "899050.BJ", search: "?debug=1" }))
      .toEqual({ recognitionEnabled: false, debugEnabled: false });
  }
});
