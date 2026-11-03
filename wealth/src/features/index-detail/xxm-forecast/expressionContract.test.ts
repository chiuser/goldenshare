import {expect,it} from "vitest";
import {validateExpression} from "../debug/forecastDebugContract";
const leaf={op:"affine",pCoefficient:0,cCoefficient:0,constant:1};
const check=(v:unknown)=>validateExpression(v,new Set(),()=>{});
it("retains original-number and finite checks for one-step expressions",()=>{
  for(const v of [leaf,{op:"macd",e12:13,e26:27,dea:0,field:"dif"},{op:"sub",args:[leaf,{op:"scale",arg:leaf,factor:2}]},{op:"round3",arg:{op:"macd",e12:13,e26:27,dea:0,field:"hist"},guard:1e-10}])expect(()=>check(v)).not.toThrow();
  for(const n of [NaN,Infinity,true,"1",null])for(const k of ["constant","pCoefficient","cCoefficient"])expect(()=>check({...leaf,[k]:n})).toThrow();
  for(const n of [NaN,Infinity,true,"1",null])expect(()=>check({op:"macd",e12:n,e26:27,dea:0,field:"dif"})).toThrow();
});
it("rejects P variables, multiple steps, unknown nodes and zero or invalid rounding guards",()=>{for(const v of [{...leaf,pCoefficient:1},{...leaf,cCoefficient:2},{op:"macd",e12:13,e26:27,dea:0,field:"dif",prefixBars:0,prefixClose:null,target:true},{op:"add",args:[leaf,leaf]},{op:"div",arg:leaf,divisor:1},{op:"round3",arg:leaf,guard:0},{op:"sub",args:[leaf]}])expect(()=>check(v)).toThrow();});
