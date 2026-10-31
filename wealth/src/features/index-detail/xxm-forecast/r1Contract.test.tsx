import {expect,it} from "vitest";
import {adaptForecast} from "./adapter";
import {decodeForecastDebug} from "../debug/forecastDebugContract";
import {forecastDebugFixture,forecastFixture} from "./forecastFixtures.test-support";
const options={period:"day" as const,debug:1 as const,decodeDebug:decodeForecastDebug,check:()=>{}};
it("accepts one next-bar condition and rejects legacy response branches instead of changing their hashes",()=>{const v=forecastDebugFixture();expect(adaptForecast(v,options).status).toBe("READY");for(const mutate of [(b:any)=>b.debug.conditions[0].referenceRole="FAR",(b:any)=>b.debug.references.nearest.priceAt="2099-01-01",(b:any)=>b.debug.farEvaluated=true,(b:any)=>b.debug.conditions.push({...b.debug.conditions[0]}),(b:any)=>b.debug.conditions[0].priceRanges[0].displayLower=1,(b:any)=>b.debug.conditions[0].priceRanges[0].upperInclusive="true",(b:any)=>b.debug.conditions[0].outcome="ZERO_RESET",(b:any)=>b.debug.conditions[0].predicates[0].left.prefixBars=0]){const bad=structuredClone(v);mutate(bad);expect(()=>adaptForecast(bad,options)).toThrow();}});
it("normal and debug responses share every public field and auxiliary details require the requested mode",()=>{const n=forecastFixture(),d=forecastDebugFixture();expect(adaptForecast(n,{...options,debug:0})).toEqual(n);const actual=adaptForecast(d,options);const {debug,...common}=actual as typeof d;expect(common).toEqual(n);expect(debug.conditions).toHaveLength(1);expect(()=>adaptForecast(d,{...options,debug:0})).toThrow();expect(()=>adaptForecast(n,options)).toThrow();});

it("rejects malformed forecast and condition identifiers without generating client IDs",()=>{
  for(const value of [true,"wrong","G".repeat(64),"f".repeat(63),"f".repeat(64)+"\n"]){
    const normal=forecastFixture();(normal as any).forecastId=value;
    expect(()=>adaptForecast(normal,{...options,debug:0})).toThrow();
    const debug=forecastDebugFixture();(debug.debug.conditions[0] as any).id=value;
    expect(()=>adaptForecast(debug,options)).toThrow();
  }
  const normal=forecastFixture();(normal as any).barsAhead=true;
  expect(()=>adaptForecast(normal,{...options,debug:0})).toThrow();
});
