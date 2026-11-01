import { expect, it } from "vitest";
import { toDetailChartPoint } from "./indexChartPointAdapter";
import type { IndexCandlePoint } from "../model/indexDetailTypes";
it("copies independently specified original fields, nulls and overlays without changing input",()=>{
  const input: IndexCandlePoint = { time:"2023-01-03",fullDate:"2023-01-03",open:100.1,high:103,low:99,close:101.2345,
    preClose:100,changePct:1.2345,amplitude:4,volume:123,volumeDisplay:"123手",amount:456,
    dif:-1.000001,dea:-2,macd:1.999998,k:20,d:30,j:0,
    ma5:1,ma10:2,ma20:3,ma30:4,ma60:5,ma90:6,ma250:null,bollUpper:7,bollMiddle:8,bollLower:9 };
  const original=structuredClone(input);
  expect(toDetailChartPoint(input)).toEqual({ time:"2023-01-03",fullDate:"2023-01-03",open:100.1,high:103,low:99,close:101.2345,
    preClose:100,changePct:1.2345,amplitude:4,volume:123,volumeDisplay:"123手",amount:456,turnoverRate:null,
    dif:-1.000001,dea:-2,macd:1.999998,k:20,d:30,j:0,
    overlays:{ma5:1,ma10:2,ma20:3,ma30:4,ma60:5,ma90:6,ma250:null,bollUpper:7,bollMiddle:8,bollLower:9}});
  expect(input).toEqual(original);
});
