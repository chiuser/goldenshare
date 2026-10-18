import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { adaptForecast } from "./adapter";
import { XxmForecastCard } from "./XxmForecastCard";
import { FORECAST_PERIODS, type ForecastResponse, type ForecastRows } from "./types";

const raw = (name: string): ForecastResponse => JSON.parse(readFileSync(resolve(process.cwd(),
  "../reports/xxm_top_activation_r2_implementation_20261019/api",name),"utf8"));

it("consumes the actual R1 route response and displays backend copy for each period", () => {
  const indexes = { day: 5, m60: 6, m90: 7, m120: 8 };
  const rows = Object.fromEntries(FORECAST_PERIODS.map(p => {
    const v = raw(`api_forecast_${indexes[p]}_${p}.json`);
    return [p,{phase:"ready",response:adaptForecast(v,p,v.requestedAsOf!),error:""}];
  })) as ForecastRows;
  const view = render(<XxmForecastCard rows={rows} retry={() => undefined} />);
  for (const p of FORECAST_PERIODS) {
    const element = view.container.querySelector(`[data-period="${p}"]`)!;
    expect(element.querySelector("p")?.textContent).toBe(rows[p].response!.display.conditionsText);
  }
});

it("preserves the real cancellation/switch split, rejects missing facts and archived a1", () => {
  const v = raw("api_forecast_13_m90.json");
  expect(adaptForecast(v,"m90",v.requestedAsOf!)).toBe(v);
  expect(v.nextBarOutcomes!.branches.some(b => b.outcome === "REFERENCE_SWITCHED")).toBe(true);
  for (const mutate of [
    (x: ForecastResponse) => { delete (x as Partial<ForecastResponse>).nextBarOutcomes; },
    (x: ForecastResponse) => { Object.assign(x,{forecastVersion:"xxm-key-point-forecast-v0.2-a1"}); },
    (x: ForecastResponse) => { Object.assign(x.nextBarOutcomes!,{debug: true}); },
    (x: ForecastResponse) => { x.nextBarOutcomes!.endpoint = x.computedThrough!; },
    (x: ForecastResponse) => { const b=x.nextBarOutcomes!.branches.find(b => b.outcome === "REFERENCE_SWITCHED")!; b.reference!.dif = x.nextBarOutcomes!.initialReference.dif; },
    (x: ForecastResponse) => { x.nextBarOutcomes!.branches[0].outcome="ZERO_RESET"; x.nextBarOutcomes!.branches[0].reference=x.nextBarOutcomes!.initialReference; },
  ]) { const bad=structuredClone(v);mutate(bad);expect(() => adaptForecast(bad,"m90",v.requestedAsOf!)).toThrow(); }
});

it("accepts fixed reactivation followed by one later reference transition, and rejects broken links", () => {
  // Structural fixture: actual route shell, literal transition. Numerical path
  // proof is covered by the independent Fraction tests, not this DTO fixture.
  const v=raw("api_forecast_9_m120.json");
  v.targetEndpoint="2026-07-14T11:30:00+08:00";v.barsAhead=3;
  v.assumption!.intermediateEndpoints=["2026-07-13T11:30:00+08:00","2026-07-13T15:00:00+08:00"];
  for (const r of v.relations) {
    const replacement={...r.initialReference,dif:r.initialReference.dif-100};
    r.referenceTransitions=[{endpoint:"2026-07-13T15:00:00+08:00",fromReference:{...r.initialReference},toReference:replacement}];
    r.reference=replacement;
  }
  for (const c of v.commonConditions) c.reference={...v.relations.find(r => r.relationId === c.relationId)!.reference};
  expect(adaptForecast(v,"m120",v.requestedAsOf!)).toBe(v);
  for (const mutate of [
    (x: ForecastResponse) => { x.relations[0].referenceTransitions[0].endpoint=x.activation!.endpoint; },
    (x: ForecastResponse) => { x.relations[0].referenceTransitions[0].endpoint=x.targetEndpoint!; },
    (x: ForecastResponse) => { x.relations[0].referenceTransitions[0].fromReference.price=1; },
    (x: ForecastResponse) => { x.relations[0].referenceTransitions[0].toReference.dif=1; },
    (x: ForecastResponse) => { x.commonConditions[0].relationId="missing"; },
    (x: ForecastResponse) => { x.examples[0].closeRanges[0].relationId="missing"; },
  ]) { const bad=structuredClone(v);mutate(bad);expect(() => adaptForecast(bad,"m120",v.requestedAsOf!)).toThrow(); }
});
