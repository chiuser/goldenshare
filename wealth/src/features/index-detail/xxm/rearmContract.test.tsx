import type { UTCTimestamp } from "lightweight-charts";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { xxmFixture } from "./xxmFixtures.test-support";
import { buildXxmViewModel, eventMarkerLabel } from "./adapter";
import { validRearmRecord } from "./rearmContract";
import { XxmResearchDetails } from "./XxmLayerUi";
import { adaptForecast } from "../xxm-forecast/adapter";
import { XxmForecastCard } from "../xxm-forecast/XxmForecastCard";
import type { ForecastResponse, ForecastRows } from "../xxm-forecast/types";
import type { XxmResponse } from "./types";

const raw = (name: string) => JSON.parse(readFileSync(resolve(process.cwd(),
  "../reports/xxm_top_activation_r2_implementation_20261019/api", name), "utf8"));
const chart = (v: XxmResponse) => v.points.map(p => ({ ...xxmFixture().points[0]!, time: (Date.parse(p.time) / 1000) as UTCTimestamp,
  fullDate: p.time, open: p.close, high: p.close, low: p.close, close: p.close, volume: 0, dif: p.dif, dea: p.dea, macd: p.hist }));

describe("a1 real route contracts", () => {
  it("validates the full API window and keeps the old waiting point separate from its later ending", () => {
    const v = raw("api_10_m120.json") as XxmResponse;
    const vm = buildXxmViewModel(v, chart(v), "m120", "000001.SH", 1);
    const gone = v.events.find(e => e.time === "2026-07-10T15:00:00+08:00" && e.type === "STRUCTURE_DISAPPEARED")!;
    expect(eventMarkerLabel(gone)).toBe("消失");
    expect(vm.markers.filter(m => m.event.time === gone.time && m.event.type === "DULL")).toHaveLength(0);
    const record = v.rearmRecords.find(r => r.id === gone.relatedRearmId)!;
    expect(record.status).toBe("REACTIVATED");
    const view = render(<XxmResearchDetails layer={{ requestKey: "a1", phase: "ready", data: vm, errorMessage: "" }} time={String(Date.parse(gone.time) / 1000)} />);
    expect(view.getByLabelText("徐小明研究指标详情")).toHaveTextContent("待重新钝化");
    expect(view.getByLabelText("徐小明研究指标详情")).toHaveTextContent("已重新钝化");
    expect(view.getByLabelText("徐小明研究指标详情")).toHaveTextContent("等待结束");
    view.unmount();
    for (const mutate of [
      (r: XxmResponse) => { delete (r as Partial<XxmResponse>).rearmRecords; },
      (r: XxmResponse) => { r.rearmRecords = []; },
      (r: XxmResponse) => { r.events.find(e => e.id === gone.id)!.relatedRearmId = null; },
      (r: XxmResponse) => { r.rearmRecords.find(r => r.id === record.id)!.reference.price += 1; },
      (r: XxmResponse) => { r.algorithmVersion = "xxm-direction-v0.1-h1"; },
    ]) {
      const broken = structuredClone(v); mutate(broken);
      expect(() => buildXxmViewModel(broken, chart(v).slice(-1), "m120", "000001.SH", 1)).toThrow();
    }
  });

  it("strictly validates record shape, reference and lifecycle across all four period formats", () => {
    const v = raw("api_9_m120.json") as XxmResponse;
    const r = v.rearmRecords.find(r => r.status === "WAITING")!;
    for (const period of ["day", "m60", "m90", "m120"] as const) {
      const copy = structuredClone(r);
      const t = (s: string) => period === "day" ? s.slice(0, 10) : s;
      for (const key of ["structureConfirmedAt", "segmentStart", "disappearedAt", "observedThrough"] as const) copy[key] = t(copy[key]);
      copy.reference.startTime = t(copy.reference.startTime); copy.reference.endTime = t(copy.reference.endTime);
      const through = t(v.source.computedThrough!);
      expect(validRearmRecord(copy, period, through)).toBe(true);
      for (const mutate of [
        (x: typeof copy) => { Object.assign(x, { referenceWave: {} }); },
        (x: typeof copy) => { x.reference.price = Infinity; },
        (x: typeof copy) => { x.observedThrough = "2099-01-01"; },
        (x: typeof copy) => { x.endReason = "zero"; },
        (x: typeof copy) => { x.status = "REACTIVATED"; },
        (x: typeof copy) => { Object.assign(x, { direction: "TOP" }); },
        (x: typeof copy) => { delete (x as Partial<typeof copy>).structureRoute; },
      ]) { const bad = structuredClone(copy); mutate(bad); expect(validRearmRecord(bad, period, through)).toBe(false); }
    }
  });

  it("renders backend waiting copy and rejects false active/confirmed states and reference reselection", () => {
    const v = raw("api_forecast_9_m120.json") as ForecastResponse;
    expect(adaptForecast(v, "m120", v.requestedAsOf!)).toBe(v);
    expect(v.rearmContext?.status).toBe("WAITING");
    expect(v.display.conditionsText).toContain("原底部结构已消失");
    const rows = Object.fromEntries(["day", "m60", "m90", "m120"].map(p => [p,
      p === "m120" ? { phase: "ready", response: v, error: "" } : { phase: "idle", response: null, error: "" }])) as ForecastRows;
    const view = render(<XxmForecastCard rows={rows} retry={() => undefined} />);
    expect(view.container.querySelector('[data-period="m120"] p')?.textContent).toBe(v.display.conditionsText);
    view.unmount();
    for (const mutate of [
      (r: ForecastResponse) => { delete (r as Partial<ForecastResponse>).rearmContext; },
      (r: ForecastResponse) => { r.status = "CONFIRMED"; },
      (r: ForecastResponse) => { r.ordinaryState = "DULL"; },
      (r: ForecastResponse) => { r.rearmContext!.status = "INVALIDATED"; },
      (r: ForecastResponse) => { r.activation!.ranges[0]!.reference.price += 1; },
      (r: ForecastResponse) => { r.relations[0]!.reference.dif += 1; },
      (r: ForecastResponse) => { Object.assign(r.rearmContext!, { referenceWave: {} }); },
    ]) { const bad = structuredClone(v); mutate(bad); expect(() => adaptForecast(bad, "m120", v.requestedAsOf!)).toThrow(); }
  });
});
