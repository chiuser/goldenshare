import {expect,it} from "vitest";
import {decodeXxmResponse,buildXxmViewModel} from "../xxm/adapter";
import {xxmDebugFixture} from "../xxm/xxmFixtures.test-support";
import {decodeXxmDebug} from "./xxmDebugContract";
const options={tsCode:"000001.SH",period:"day" as const,debug:1 as const,decodeDebug:decodeXxmDebug,check:()=>{}};
it("rejects hanging IDs, wrong references, future facts and mismatched public/debug order",()=>{const r=xxmDebugFixture().response;for(const mutate of [(v:any)=>v.debug.points[0].activeStructureId="missing",(v:any)=>v.debug.events.reverse(),(v:any)=>v.debug.events[0].relatedStructureId="missing",(v:any)=>v.debug.events[0].eventReference={...v.debug.events[0].eventReference,dif:42},(v:any)=>v.debug.structures[0].firstOppositeAt="2099-01-01",(v:any)=>v.debug.structures[0].originWave.priceAt="2023-01-12",(v:any)=>v.debug.structures.push({...v.debug.structures[0]}),(v:any)=>v.debug.events[1].route="reactivation",(v:any)=>v.events[0].displayOnChart=true]){const bad=structuredClone(r);mutate(bad);expect(()=>decodeXxmResponse(bad,options)).toThrow();}});
it("retains a structure in a no-event window without inventing a current ordinary structure",()=>{const {response,points}=xxmDebugFixture();response.events=[];response.debug.events=[];response.points[0]!.ordinaryState="NONE";response.points[0]!.ordinaryDirection=null;response.debug.points[0]!.activeReference=null;const s=response.debug.structures[0]!;s.status="FOLLOWING";s.trackingEndedAt=s.disappearedAt=s.disappearanceReason=null;s.trackingPriceExtreme=103;const decoded=decodeXxmResponse(response,options);const vm=buildXxmViewModel(decoded,points,"day","000001.SH");expect(vm.byTime.get(points[0]!.fullDate)?.debugDetail?.structures).toHaveLength(1);expect(vm.byTime.get(points[0]!.fullDate)?.point.ordinaryState).toBe("NONE");});
it("accepts color-flip formation after the old wave ended and rejects contradictory lifecycle facts",()=>{
  const {response}=xxmDebugFixture();response.events=[];response.debug.events=[];
  response.points[0]!.ordinaryState="NONE";response.points[0]!.ordinaryDirection=null;response.debug.points[0]!.activeReference=null;
  const s=response.debug.structures[0]!;s.formationRoute="color_flip";s.formedAt="2023-01-10";s.status="FOLLOWING";
  s.trackingEndedAt=s.disappearedAt=s.disappearanceReason=null;s.trackingPriceExtreme=103;
  expect(()=>decodeXxmResponse(response,options)).not.toThrow();
  for(const mutate of [(v:any)=>v.debug.structures[0].trackingPriceExtreme=104,(v:any)=>v.debug.structures[0].formedAt="2023-01-09",(v:any)=>v.debug.structures[0].nextSameColorStart="2023-01-10",(v:any)=>v.debug.structures[0].originWave.sign=true]){
    const bad=structuredClone(response);mutate(bad);expect(()=>decodeXxmResponse(bad,options)).toThrow();
  }
});
it("compares reference fields independently of JSON property ordering",()=>{
  const {response}=xxmDebugFixture();const ref=response.debug.events[0]!.eventReference;
  response.debug.events[0]!.eventReference=Object.fromEntries(Object.entries(ref).reverse()) as typeof ref;
  expect(()=>decodeXxmResponse(response,options)).not.toThrow();
});
