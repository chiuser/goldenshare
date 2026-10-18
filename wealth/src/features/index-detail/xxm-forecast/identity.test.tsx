import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import { XXM_ALGORITHM_VERSION, XXM_SPEC_HASH } from "../xxm/types";
import { xxmFixture } from "../xxm/xxmFixtures.test-support";
import { buildXxmViewModel } from "../xxm/adapter";
import { adaptForecast } from "./adapter";
import { XXM_FORECAST_VERSION, XXM_FORECAST_SPEC_HASH, type ForecastResponse } from "./types";

const raw = (folder: string, name: string): ForecastResponse => JSON.parse(readFileSync(resolve(process.cwd(),"../reports",folder,name),"utf8"));
const current=()=>raw("xxm_top_activation_r2_implementation_20261019/api","api_forecast_5_day.json");

it("uses the independent approved r2 identities and rejects old or mixed hashes",()=>{
  expect(XXM_ALGORITHM_VERSION).toBe("xxm-direction-v0.1-r2");
  expect(XXM_SPEC_HASH).toBe("6db425730c72f22ea756c121a832f27c966d1324ef0a72a2312a3c572038724d");
  expect(XXM_FORECAST_VERSION).toBe("xxm-key-point-forecast-v0.3-r2");
  expect(XXM_FORECAST_SPEC_HASH).toBe("add5e3636e6972e267bdda81c05e0e864f600f9e67d658b6a560445e39dda6d8");
  const value=current();expect(adaptForecast(value,"day",value.requestedAsOf!)).toBe(value);
  for(const field of ["detectorSpecHash","forecastSpecHash"] as const){
    const bad=structuredClone(value);bad[field]="a".repeat(64);
    expect(()=>adaptForecast(bad,"day",bad.requestedAsOf!)).toThrow();
  }
  const old=raw("xxm_reference_rescue_r1_implementation_20261017/api_02","api_forecast_5_day.json");
  expect(()=>adaptForecast(old,"day",old.requestedAsOf!)).toThrow();
  const {response,points}=xxmFixture();
  expect(()=>buildXxmViewModel(response,points,"day","000001.SH")).not.toThrow();
  response.specHash="a".repeat(64);
  expect(()=>buildXxmViewModel(response,points,"day","000001.SH")).toThrow();
});

it("accepts the new exclusion only for inactive TOP activation and rejects misplaced values",()=>{
  // Structural response fixture, not a price or original-software assertion.
  const value=current();
  Object.assign(value,{ordinaryState:"NONE",direction:"TOP",status:"NO_CANDIDATE",reasonCode:"NO_ENTRY_RANGE",rearmContext:null,
    nextBarOutcomes:null,targetEndpoint:null,barsAhead:null,assumption:null,relations:[],commonConditions:[],examples:[],
    targetEntryRanges:[],targetEntryExclusions:[],confirmedAt:null,confirmedDirection:null,
    activation:{endpoint:"2026-10-14",ranges:[],exclusions:[{priceRange:{lower:0,upper:null,lowerInclusive:false,upperInclusive:false},reason:"CURRENT_DIF_NOT_POSITIVE"}]}});
  expect(adaptForecast(value,"day",value.requestedAsOf!)).toBe(value);
  for(const mutation of [{direction:"BOTTOM"},{ordinaryState:"DULL"},{ordinaryState:"STRUCTURE"},{dataStatus:"DELAYED"},{status:"READY"},{reasonCode:"CURRENT_DIF_NOT_POSITIVE"}]){
    const bad=structuredClone(value);Object.assign(bad,mutation);
    expect(()=>adaptForecast(bad,"day",bad.requestedAsOf!)).toThrow();
  }
  const unknown=structuredClone(value);unknown.activation!.exclusions[0].reason="UNKNOWN";
  expect(()=>adaptForecast(unknown,"day",unknown.requestedAsOf!)).toThrow();
  const wrong=structuredClone(value);
  wrong.targetEntryExclusions=[{entryRangeIds:[],priceRange:value.activation!.exclusions[0].priceRange,reason:"CURRENT_DIF_NOT_POSITIVE"}];
  expect(()=>adaptForecast(wrong,"day",wrong.requestedAsOf!)).toThrow();
});
