import {expect,it} from "vitest";
import {decodeXxmResponse} from "./adapter";
import {goldXxmFixture as xxmFixture} from "./xxmFixtures.test-support";
it("rejects removed waiting and reactivation contracts rather than accepting empty legacy fields",()=>{const r=xxmFixture("000001.SH").response;for(const patch of [{rearmRecords:[]},{bottomHistories:[]},{topHistories:[]}])expect(()=>decodeXxmResponse({...r,...patch},{tsCode:"000001.SH",period:"day",check:()=>{}})).toThrow();const bad=structuredClone(r) as any;bad.points[0].pendingRearmId="waiting";expect(()=>decodeXxmResponse(bad,{tsCode:"000001.SH",period:"day",check:()=>{}})).toThrow();});
