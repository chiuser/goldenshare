import { expect, it } from "vitest";
import type { CurvePoint } from "../api/generatedContracts";
import { returnChart } from "./returnChart";
const point = (amount: string|null): CurvePoint => ({ periodStartDate:"2026-09-11",periodEndDate:"2026-09-11",isPeriodEnded:true,
  profitAmount:amount,capitalAmount:amount===null?null:"10000.00",returnPct:amount===null?null:"0.00",
  dataStatus:amount===null?"Delayed":"Ready",reason:amount===null?"待计算":null,isFinal:amount!==null,accounts:[] });
it("keeps missing points as gaps, real zero as a point and signed zero axis",()=>{
  const chart = returnChart([point("-100.00"),point(null),point("0.00"),point("200.00")],"AMOUNT");
  expect(chart.points.map(p=>p.y===null)).toEqual([false,true,false,false]);
  expect(chart.ticks.some(t=>t.zero)).toBe(true);
  expect(chart.points[0].y).toBeGreaterThan(chart.points[3].y!);
});
it("scales huge exact values without converting money into an unsafe Number",()=>{
  const chart = returnChart([point("-999999999999999999.99"),point("0.00"),point("999999999999999999.99")],"AMOUNT");
  expect(chart.points.map(p=>p.y)).toEqual([330,175,20]);
  expect(chart.ticks[0].text).toBe("+999,999,999,999,999,999.99");
});
