import {expect,it} from "vitest";
import {XXM_ALGORITHM_VERSION,XXM_SPEC_HASH} from "../xxm/types";
import {XXM_FORECAST_VERSION,XXM_FORECAST_SPEC_HASH} from "./types";
import {forecastFixture} from "./forecastFixtures.test-support";
import {adaptForecast} from "./adapter";
const options={period:"day" as const,debug:0 as const,check:()=>{}};
it("uses the accepted complete r4 identities, rejects old or mixed identities and missing fields",()=>{
  expect(XXM_ALGORITHM_VERSION).toBe("xxm-direction-v0.4-r4");expect(XXM_SPEC_HASH).toBe("db435b39a3d198c126bfff567dfbe66faf74ff9299005578ec6b49bf065fd110");expect(XXM_FORECAST_VERSION).toBe("xxm-key-point-forecast-v0.6-r4");expect(XXM_FORECAST_SPEC_HASH).toBe("9994790178d64757462643fc37eba9e0945b118e91f1fdb85223db81db2a7b12");
  expect(adaptForecast(forecastFixture(),options).status).toBe("READY");
  for(const field of ["forecastSpecHash","detectorSpecHash","forecastVersion"]){expect(()=>adaptForecast({...forecastFixture(),[field]:"old"},options)).toThrow();}
  for(const field of Object.keys(forecastFixture())){const bad:any=forecastFixture();delete bad[field];expect(()=>adaptForecast(bad,options)).toThrow();}
});
it("rejects stale asOf/period and removed multi-step or waiting success fields",()=>{expect(()=>adaptForecast(forecastFixture("m60"),options)).toThrow();expect(()=>adaptForecast(forecastFixture(),{...options,asOf:"2023-01-09"})).toThrow();for(const patch of [{activation:null},{relations:[]},{rearmContext:null},{nextBarOutcomes:null},{status:"CONFIRMED"},{status:"ENTRY_ONLY"},{barsAhead:2}])expect(()=>adaptForecast({...forecastFixture(),...patch},options)).toThrow();});
