import {expect,it} from "vitest";
import {adaptForecast} from "./adapter";
import {decodeDebugForecast} from "../debug/apiClient";
import {forecastDebugFixture,forecastFixture} from "./forecastFixtures.test-support";
const options={tsCode:"000001.SH",period:"day" as const,check:()=>{}};
it("accepts one next-bar condition and rejects legacy response branches instead of changing their hashes",()=>{const v=forecastDebugFixture("000001.SH");expect(decodeDebugForecast(v,options).status).toBe("READY");for(const mutate of [(b:any)=>b.debug.conditions[0].referenceRole="FAR",(b:any)=>b.debug.references.nearest.priceAt="2099-01-01",(b:any)=>b.debug.farEvaluated=true,(b:any)=>b.debug.conditions.push({...b.debug.conditions[0]}),(b:any)=>b.debug.conditions[0].priceRanges[0].displayLower=1,(b:any)=>b.debug.conditions[0].priceRanges[0].upperInclusive="true",(b:any)=>b.debug.conditions[0].outcome="ZERO_RESET",(b:any)=>b.debug.conditions[0].predicates[0].left.prefixBars=0]){const bad=structuredClone(v);mutate(bad);expect(()=>decodeDebugForecast(bad,options)).toThrow();}});
it.each(["day","m30","m60","m90","m120"] as const)("normal and debug %s responses share every public field and require the requested mode",period=>{const tsCode="399001.SZ",request={...options,tsCode,period};const n=forecastFixture(tsCode,period),d=forecastDebugFixture(tsCode,period);expect(adaptForecast(n,{...request})).toEqual(n);const actual=decodeDebugForecast(d,request);const {debug,...common}=actual as typeof d;expect(common).toEqual(n);expect(debug.conditions).toHaveLength(1);expect(()=>adaptForecast(d,{...request})).toThrow();expect(()=>decodeDebugForecast(n,request)).toThrow();});

it("rejects malformed forecast and condition identifiers without generating client IDs",()=>{
  for(const value of [true,"wrong","G".repeat(64),"f".repeat(63),"f".repeat(64)+"\n"]){
    const normal=forecastFixture("000001.SH");(normal as any).forecastId=value;
    expect(()=>adaptForecast(normal,{...options})).toThrow();
    const debug=forecastDebugFixture("000001.SH");(debug.debug.conditions[0] as any).id=value;
    expect(()=>decodeDebugForecast(debug,options)).toThrow();
  }
  const normal=forecastFixture("000001.SH");(normal as any).barsAhead=true;
  expect(()=>adaptForecast(normal,{...options})).toThrow();
});
