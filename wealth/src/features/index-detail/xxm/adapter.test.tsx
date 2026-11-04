import {render,screen} from "@testing-library/react";
import {expect,it} from "vitest";
import {buildXxmViewModel,decodeXxmResponse,timeKey} from "./adapter";
import {decodeXxmDebug} from "../debug/xxmDebugContract";
import {xxmFixture,xxmDebugFixture} from "./xxmFixtures.test-support";
import {XxmSignalDetails} from "./XxmLayerUi";
import {XxmDebugDetails} from "../debug/XxmDebugDetails";
import type { XxmPeriod } from "./types";
const options={tsCode:"000001.SH",period:"day" as const,debug:0 as const,check:()=>{}};
it("decodes an ordinary response without any research fields and matches original chart values",()=>{const {response,points}=xxmFixture("000001.SH");const decoded=decodeXxmResponse(response,options);const vm=buildXxmViewModel(decoded,points,"day","000001.SH");expect(vm.markers).toHaveLength(2);expect(vm.byTime.get("2023-01-12")?.debugDetail).toBeNull();for(const key of ["close","dif","dea","macd"] as const){const changed=points.map(p=>({...p,[key]:Number(p[key])+.00001}));expect(()=>buildXxmViewModel(decoded,changed,"day","000001.SH")).toThrow();}});
it("keeps both same-time facts but draws and normally describes only the authorized new dulling",()=>{const {response,points}=xxmDebugFixture("000001.SH");const decoded=decodeXxmResponse(response,{...options,debug:1,decodeDebug:decodeXxmDebug});const data=buildXxmViewModel(decoded,points,"day","000001.SH");const detail=data.byTime.get("2023-01-12")!;expect(detail.events).toHaveLength(2);expect(detail.displayEvents).toHaveLength(1);expect(data.markers.map(m=>m.event.id)).toEqual(["activate-new"]);const layer={phase:"ready" as const,requestKey:"current",data,errorMessage:""};render(<><XxmSignalDetails layer={layer} time="2023-01-12"/><XxmDebugDetails layer={layer} time="2023-01-12"/></>);expect(screen.getByLabelText("顶底识别详情")).toHaveTextContent("顶钝化");expect(screen.getByLabelText("顶底识别详情")).not.toHaveTextContent("消失");expect(screen.getByLabelText("顶底识别核验依据")).toHaveTextContent("cancel-old");});
it("rejects incorrect identity, illegal values, unordered points and missing display flags",()=>{const base=xxmFixture("000001.SH").response;const mutations=[(v:any)=>v.specHash="old",(v:any)=>v.algorithmVersion="xxm-direction-v0.1-r2",(v:any)=>v.points[0].dif=NaN,(v:any)=>v.points[0].close=true,(v:any)=>v.points.push({...v.points[0]}),(v:any)=>delete v.events[0].displayOnChart,(v:any)=>v.events[0].displayOnChart=1,(v:any)=>v.events.push({...v.events[0]}),(v:any)=>v.points[0].ordinaryState="WAITING",(v:any)=>v.points[0].time="2023-02-30",(v:any)=>v.source.inputId="old",(v:any)=>v.rearmRecords=[]];for(const mutate of mutations){const bad=structuredClone(base);mutate(bad);expect(()=>decodeXxmResponse(bad,options)).toThrow();}});
it("handles source EMPTY and DELAYED without turning errors into empty",()=>{const r=xxmFixture("000001.SH").response;const empty={...r,points:[],events:[],source:{...r.source,startTime:null,computedThrough:null},meta:{count:0,responseStart:null,responseEnd:null},dataStatus:{status:"EMPTY",message:null,asOf:null}};expect(decodeXxmResponse(empty,options).dataStatus.status).toBe("EMPTY");expect(decodeXxmResponse({...r,dataStatus:{...r.dataStatus,status:"DELAYED",message:"来源滞后"}},options).dataStatus.status).toBe("DELAYED");expect(()=>decodeXxmResponse({...empty,events:r.events},options)).toThrow();});
it("rejects auxiliary payloads in ordinary mode and unavailable decoders",()=>{const r=xxmDebugFixture("000001.SH").response;expect(()=>decodeXxmResponse(r,options)).toThrow();expect(()=>decodeXxmResponse(r,{...options,debug:1})).toThrow();});

const periods = ["day", "m30", "m60", "m90", "m120"] as const;
it.each(periods)("binds nonempty ordinary/debug facts and chart values to the requested index in %s", period => {
  const tsCode = "399001.SZ";
  const { response, points } = xxmDebugFixture(tsCode, period);
  const { debug: expectedDebug, ...ordinary } = response;
  const contract = { tsCode, period, check: () => {} };
  const decoded = decodeXxmResponse(response, { ...contract, debug: 1, decodeDebug: decodeXxmDebug });
  const normal = decodeXxmResponse(ordinary, { ...contract, debug: 0 });
  const { debug, ...publicFacts } = decoded as typeof response;
  expect(publicFacts).toEqual(normal);
  expect(debug).toEqual(expectedDebug);
  const data = buildXxmViewModel(decoded, points, period, tsCode, period === "day" ? null : 1);
  expect(data.markers.map(marker => marker.event.id)).toEqual(["activate-new"]);
  expect(data.byTime.get(String(points[0]!.time))?.debugDetail?.structures.map(s => s.id)).toEqual(["old-structure"]);
  expect(() => decodeXxmResponse(response, { ...contract, tsCode: "000001.SH", debug: 1, decodeDebug: decodeXxmDebug })).toThrow();
  expect(() => buildXxmViewModel(decoded, points, period, "000001.SH", period === "day" ? null : 1)).toThrow();
  expect(() => decodeXxmResponse(response, { ...contract, period: period === "m30" ? "m60" : "m30", debug: 1, decodeDebug: decodeXxmDebug })).toThrow();
  if (period !== "day") expect(() => buildXxmViewModel(decoded, points, period, tsCode, 2)).toThrow();
  for (const key of ["close", "dif", "dea", "macd"] as const) {
    const changed = points.map(point => ({ ...point, [key]: Number(point[key]) + 0.00001 }));
    expect(() => buildXxmViewModel(decoded, changed, period, tsCode, period === "day" ? null : 1)).toThrow();
  }
});

// Independent literal completed endpoints from the major-index minute producer
// contract, also frozen in expansion LLD §5; do not derive from timeKey.
it.each(["10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"])("accepts the m30 completed endpoint %s", endpoint => {
  const stamp = `2026-11-03T${endpoint}:00+08:00`;
  expect(timeKey(stamp, "m30")).toBe(String(Date.parse(stamp) / 1000));
});
it.each(["09:30", "12:00", "13:00", "15:30"])("rejects %s as an m30 completed endpoint", endpoint => {
  expect(() => timeKey(`2026-11-03T${endpoint}:00+08:00`, "m30")).toThrow();
});
it("does not use another minute period's endpoints or a fallback for an unsupported period", () => {
  expect(() => timeKey("2026-11-03T10:00:00+08:00", "m60")).toThrow();
  expect(() => timeKey("2026-11-03T10:30:00+08:00", "m90")).toThrow();
  expect(() => timeKey("2026-11-03T14:00:00+08:00", "m120")).toThrow();
  expect(() => timeKey("2026-11-03T11:30:00+08:00", "m15" as XxmPeriod)).toThrow();
  expect(() => timeKey("2026-11-03T10:00:00+00:00", "m30")).toThrow();
});
