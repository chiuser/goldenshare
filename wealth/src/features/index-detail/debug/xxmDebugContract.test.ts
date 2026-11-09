import {expect,it} from "vitest";
import {decodeDebugXxmResponse as decodeXxmResponse,buildDebugXxmViewModel as buildXxmViewModel} from "./xxmAdapter";
import {xxmDebugFixture} from "../xxm/xxmFixtures.test-support";
import {decodeXxmDebug} from "./xxmDebugContract";
const options={tsCode:"000001.SH",period:"day" as const,debug:1 as const,decodeDebug:decodeXxmDebug,check:()=>{}};
it("rejects hanging IDs, wrong references, future facts and mismatched public/debug order",()=>{const r=xxmDebugFixture("000001.SH").response;for(const mutate of [(v:any)=>v.debug.points[0].activeStructureId="missing",(v:any)=>v.debug.events.reverse(),(v:any)=>v.debug.events[0].relatedStructureId="missing",(v:any)=>v.debug.events[0].eventReference={...v.debug.events[0].eventReference,dif:42},(v:any)=>v.debug.structures[0].firstOppositeAt="2099-01-01",(v:any)=>v.debug.structures[0].originWave.priceAt="2023-01-12",(v:any)=>v.debug.structures.push({...v.debug.structures[0]}),(v:any)=>v.debug.events[1].route="reactivation",(v:any)=>v.events[0].displayOnChart=true]){const bad=structuredClone(r);mutate(bad);expect(()=>decodeXxmResponse(bad,options)).toThrow();}});
it("retains a structure in a no-event window without inventing a current ordinary structure",()=>{const {response,points}=xxmDebugFixture("000001.SH");response.events=[];response.debug.events=[];response.points[0]!.ordinaryState="NONE";response.points[0]!.ordinaryDirection=null;response.debug.points[0]!.activeReference=null;const s=response.debug.structures[0]!;s.status="FOLLOWING";s.trackingEndedAt=s.disappearedAt=s.disappearanceReason=null;s.trackingPriceExtreme=103;const decoded=decodeXxmResponse(response,options);const vm=buildXxmViewModel(decoded,points,"day","000001.SH");expect(vm.byTime.get(points[0]!.fullDate)?.debugDetail?.structures).toHaveLength(1);expect(vm.byTime.get(points[0]!.fullDate)?.point.ordinaryState).toBe("NONE");});
it("accepts color-flip formation after the old wave ended and rejects contradictory lifecycle facts",()=>{
  const {response}=xxmDebugFixture("000001.SH");response.events=[];response.debug.events=[];
  response.points[0]!.ordinaryState="NONE";response.points[0]!.ordinaryDirection=null;response.debug.points[0]!.activeReference=null;
  const s=response.debug.structures[0]!;s.formationRoute="color_flip";s.formedAt="2023-01-10";s.status="FOLLOWING";
  s.trackingEndedAt=s.disappearedAt=s.disappearanceReason=null;s.trackingPriceExtreme=103;
  expect(()=>decodeXxmResponse(response,options)).not.toThrow();
  for(const mutate of [(v:any)=>v.debug.structures[0].trackingPriceExtreme=104,(v:any)=>v.debug.structures[0].formedAt="2023-01-09",(v:any)=>v.debug.structures[0].nextSameColorStart="2023-01-10",(v:any)=>v.debug.structures[0].originWave.sign=true]){
    const bad=structuredClone(response);mutate(bad);expect(()=>decodeXxmResponse(bad,options)).toThrow();
  }
});
it("compares reference fields independently of JSON property ordering",()=>{
  const {response}=xxmDebugFixture("000001.SH");const ref=response.debug.events[0]!.eventReference;
  response.debug.events[0]!.eventReference=Object.fromEntries(Object.entries(ref).reverse()) as typeof ref;
  expect(()=>decodeXxmResponse(response,options)).not.toThrow();
});

it.each(["day", "m30", "m60", "m90", "m120"] as const)("decodes a non-Shanghai index's complete %s auxiliary facts without enabling research", period => {
  const { response, points } = xxmDebugFixture("399006.SZ", period);
  const decoded = decodeXxmResponse(response, { ...options, tsCode: "399006.SZ", period });
  const data = buildXxmViewModel(decoded, points, period, "399006.SZ", period === "day" ? null : 1);
  const details = data.byTime.get(String(points[0]!.time))!;
  expect(details.debugDetail?.events.map(event => event.id)).toEqual(["cancel-old", "activate-new"]);
  expect(details.debugDetail?.structures.map(structure => structure.id)).toEqual(["old-structure"]);
  expect(details.displayEvents.map(event => event.id)).toEqual(["activate-new"]);
  const bad = structuredClone(response);
  bad.debug.events[0]!.relatedStructureId = "missing";
  expect(() => decodeXxmResponse(bad, { ...options, tsCode: "399006.SZ", period })).toThrow();
});

it.each(["TOP", "BOTTOM"] as const)("preserves three same-bar events for a %s reactivation", direction => {
  const { response, points } = xxmDebugFixture("000001.SH");
  const oldEvent = response.events[0]!, activation = response.events[1]!;
  const oldRecord = response.debug.structures[0]!;
  const sign = direction === "TOP" ? 1 : -1;
  const near = { ...response.debug.events[1]!.eventReference, price: sign === 1 ? 103 : 110, dif: sign * 100 };
  const far = { ...oldRecord.originalReference, price: sign === 1 ? 100 : 120, dif: sign * 200 };
  oldEvent.displayOnChart = direction !== oldEvent.direction;
  activation.direction = direction;
  const cancel = { ...oldEvent, id: "cancel-assessing", direction, displayOnChart: false };
  response.events = [oldEvent, cancel, activation];
  response.debug.events.splice(1, 0, {
    id: cancel.id, route: "dif_break", fromState: "STRUCTURE", eventReference: near, relatedStructureId: "assessing",
  });
  response.debug.events[2]!.eventReference = far;
  response.points[0]!.ordinaryDirection = direction;
  Object.assign(response.points[0]!, { dif: sign * 150, dea: sign * 149, hist: sign * 2 });
  Object.assign(points[0]!, { dif: sign * 150, dea: sign * 149, macd: sign * 2 });
  response.debug.points[0]!.activeReference = far;
  response.debug.structures.push({
    ...oldRecord, id: "assessing", direction, structureEventId: "assessing-formation", formedAt: "2023-01-11",
    originSegmentStart: "2023-01-10", originalReference: near, priceExtremeAt: "2023-01-11",
    originWave: null, firstOppositeAt: null, nextSameColorStart: null, nextSameColorCount: 0,
    trackingPriceExtreme: null, trackingPriceExtremeAt: null, disappearanceReason: "reference_dif_break",
  });
  const decoded = decodeXxmResponse(response, options);
  const row = buildXxmViewModel(decoded, points, "day", "000001.SH").byTime.get(points[0]!.fullDate)!;
  expect(row.debugDetail?.events.map(event => event.id)).toEqual(["cancel-old", "cancel-assessing", "activate-new"]);
  expect(row.displayEvents.map(event => event.id)).toEqual(direction === "TOP" ? ["activate-new"] : ["cancel-old", "activate-new"]);
  const bad = structuredClone(response);
  bad.events.reverse();
  bad.debug.events.reverse();
  expect(() => decodeXxmResponse(bad, options)).toThrow();
});
