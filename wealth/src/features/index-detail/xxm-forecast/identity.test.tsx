import {expect,it} from "vitest";
import {XXM_ALGORITHM_VERSION,XXM_SPEC_HASH} from "../xxm/types";
import {XXM_FORECAST_VERSION,XXM_FORECAST_SPEC_HASH} from "./types";
import {forecastFixture} from "./forecastFixtures.test-support";
import {adaptForecast} from "./adapter";
const options={tsCode:"000001.SH",period:"day" as const,debug:0 as const,check:()=>{}};
it("uses the accepted complete r4 identities, rejects old or mixed identities and missing fields",()=>{
  expect(XXM_ALGORITHM_VERSION).toBe("xxm-direction-v0.4-r4");expect(XXM_SPEC_HASH).toBe("db435b39a3d198c126bfff567dfbe66faf74ff9299005578ec6b49bf065fd110");expect(XXM_FORECAST_VERSION).toBe("xxm-key-point-forecast-v0.6-r4");expect(XXM_FORECAST_SPEC_HASH).toBe("9994790178d64757462643fc37eba9e0945b118e91f1fdb85223db81db2a7b12");
  expect(adaptForecast(forecastFixture("000001.SH"),options).status).toBe("READY");
  for(const field of ["forecastSpecHash","detectorSpecHash","forecastVersion"]){expect(()=>adaptForecast({...forecastFixture("000001.SH"),[field]:"old"},options)).toThrow();}
  for(const field of Object.keys(forecastFixture("000001.SH"))){const bad:any=forecastFixture("000001.SH");delete bad[field];expect(()=>adaptForecast(bad,options)).toThrow();}
});
it("rejects stale code/asOf/period and removed multi-step or waiting success fields",()=>{expect(()=>adaptForecast(forecastFixture("399001.SZ"),options)).toThrow();expect(()=>adaptForecast(forecastFixture("000001.SH","m60"),options)).toThrow();expect(()=>adaptForecast(forecastFixture("000001.SH"),{...options,asOf:"2023-01-09"})).toThrow();for(const patch of [{activation:null},{relations:[]},{rearmContext:null},{nextBarOutcomes:null},{status:"CONFIRMED"},{status:"ENTRY_ONLY"},{barsAhead:2}])expect(()=>adaptForecast({...forecastFixture("000001.SH"),...patch},options)).toThrow();});

it("binds a non-Shanghai m30 replay to its requested code, period and asOf",()=>{
  const asOf="2023-01-10T15:00:00+08:00";
  const response=forecastFixture("399001.SZ","m30",asOf);
  const request={...options,tsCode:"399001.SZ",period:"m30" as const,asOf};
  expect(adaptForecast(response,request)).toEqual(response);
  expect(response.targetEndpoint).toBe("2023-01-11T10:00:00+08:00");
  for(const patch of [{tsCode:"000001.SH"},{period:"m60"},{requestedAsOf:"2023-01-10T14:30:00+08:00"},{mode:"LATEST"}])
    expect(()=>adaptForecast({...response,...patch},request)).toThrow();
  // Formal m30 endpoints from the expansion LLD §5, independent of timeKey.
  for(const [through,target] of [
    ["2023-01-10T10:00:00+08:00","2023-01-10T10:30:00+08:00"],
    ["2023-01-10T10:30:00+08:00","2023-01-10T11:00:00+08:00"],
    ["2023-01-10T11:00:00+08:00","2023-01-10T11:30:00+08:00"],
    ["2023-01-10T11:30:00+08:00","2023-01-10T13:30:00+08:00"],
    ["2023-01-10T13:30:00+08:00","2023-01-10T14:00:00+08:00"],
    ["2023-01-10T14:00:00+08:00","2023-01-10T14:30:00+08:00"],
    ["2023-01-10T14:30:00+08:00","2023-01-10T15:00:00+08:00"],
    ["2023-01-10T15:00:00+08:00","2023-01-11T10:00:00+08:00"],
  ]){
    const sample=forecastFixture("399001.SZ","m30",through);
    sample.targetEndpoint=target;
    sample.display.targetText=`${target} 收盘 · 下一根条件`;
    expect(()=>adaptForecast(sample,{...request,asOf:through})).not.toThrow();
  }
  for(const stamp of ["2023-01-10T09:30:00+08:00","2023-01-10T12:00:00+08:00","2023-01-10T10:00:00Z"])
    expect(()=>adaptForecast({...response,computedThrough:stamp},request)).toThrow();
  expect(()=>adaptForecast({...response,targetEndpoint:"2023-01-11T09:30:00+08:00"},request)).toThrow();
});
