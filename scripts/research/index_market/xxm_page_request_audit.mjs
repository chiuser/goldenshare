// Real P4 clients, in-memory compilation, one original scheduler per tab.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { AsyncLocalStorage } from "node:async_hooks";
import { createHash } from "node:crypto";
const require = createRequire(new URL("../../../wealth/package.json", import.meta.url));
const { build } = require("esbuild");
const root = fileURLToPath(new URL("../../../", import.meta.url));
const [base, rawGroup] = process.argv.slice(2);
const group = JSON.parse(rawGroup);
assert(base && group && ["normal", "debug"].includes(group.mode));
const prefix = `${root}wealth/src/features/index-detail/`;
const entry = [
  ["api/indexDetailApiClient.ts", "fetchIndexDetailMinutes, fetchIndexDetailMinuteIndicators, fetchIndexDetailKline"],
  ["api/indexNineTurnLoader.ts", "loadIndexNineTurnSeries"],
  ["api/indexDetailRequestScheduler.ts", "indexDetailRequests"],
  ["model/indexDetailConstants.ts", "INDEX_DAILY_HISTORY_LIMIT"],
  ["xxm/adapter.ts", "buildXxmViewModel"],
  ["api/indexMinuteViewModelAdapter.ts", "buildIndexMinuteChartViewModel"],
  ["xxm/apiClient.ts", "fetchXxm, checkRequest, XXM_TIMEOUT_MS"],
  ["xxm-forecast/apiClient.ts", "fetchForecast"],
  ...(group.mode === "debug" ? [
    ["debug/xxmDebugContract.ts", "decodeXxmDebug"], ["debug/forecastDebugContract.ts", "decodeForecastDebug"],
  ] : []),
].map(([path,names]) => `export { ${names} } from ${JSON.stringify(prefix+path)};`).join("\n");
const compiled = await build({stdin:{contents:entry,resolveDir:root,sourcefile:"xxm-p4-audit.ts"},
  bundle:true,write:false,platform:"node",format:"esm",logLevel:"silent"});
const bundle = `data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`;
const tabCount = group.scenario === "mixed_two" ? 2 : 1;
const tabs = await Promise.all(Array.from({length:tabCount},(_,i)=>import(bundle+`#tab${i+1}`)));
const nativeFetch = globalThis.fetch;
const context = new AsyncLocalStorage();
// The original queue saves callbacks and executes them from a shared pump.
// Bind only the observation context; preserve one original run and its policy.
for (const tab of tabs) {
  const run = tab.indexDetailRequests.run.bind(tab.indexDetailRequests);
  tab.indexDetailRequests.run = (kind, work, signal) => {
    const owner = context.getStore();
    return run(kind, () => context.run(owner, work), signal);
  };
}
const requests = new Map(), sequences = new Map();
const controller = new AbortController();
const digest = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");
globalThis.window = {location:{origin:base},localStorage:{getItem:()=>null},setTimeout,clearTimeout,dispatchEvent(){}};
const known = new Set(["kline","minutes","minute-indicators","nine-turn","minute-nine-turn","xxm-signals","minute-xxm-signals","xxm-key-point-forecast"]);
globalThis.fetch = async(input, options={}) => {
  const url = new URL(String(input),base), owner=context.getStore();
  assert(owner && known.has(url.pathname.split("/").at(-1)),"Unexpected product request");
  const sequence=(sequences.get(owner.tabId)??0)+1;sequences.set(owner.tabId,sequence);
  const requestId=`${group.groupId}:${group.scenario}:${owner.round}:${owner.tabId}:${sequence}`;
  const row={requestId,httpSeconds:null,clientSeconds:null,terminal:null,httpStatus:null,bodyBytes:0,
    computedThrough:null,responseRows:null,windowStart:null,windowEnd:null};
  requests.set(requestId,row);owner.requestId=requestId;
  const headers = new Headers(options.headers);headers.set("X-Request-ID",requestId);
  const started=performance.now();
  try {
    const response=await nativeFetch(url,{...options,headers});
    row.httpStatus=response.status;
    const bytes=await response.arrayBuffer();
    row.httpSeconds=(performance.now()-started)/1000;row.bodyBytes=bytes.byteLength;
    assert.equal(response.headers.get("x-request-id"),requestId);
    // The real client consumes this body once. No clone, second fetch or parse.
    return new Response(bytes,{status:response.status,statusText:response.statusText,headers:response.headers});
  } catch(error) {row.terminal=options.signal?.aborted?"cancelled":"error";throw error;}
};
async function execute(tab,tabId,round,work,{r4=false,adapt}={}) {
  const owner={tabId:String(tabId),round,requestId:null};
  return context.run(owner,async()=>{
    try {
      const result=await work();
      const row=requests.get(owner.requestId);assert(row);
      if(r4){
        const {response,deadline}=result;
        tab.checkRequest(controller.signal,deadline);
        if(adapt) adapt(response,()=>tab.checkRequest(controller.signal,deadline));
        // Build the bounded per-request summary before the original final check.
        row.computedThrough=response.computedThrough??response.source?.computedThrough??null;
        if(response.points){row.responseRows=response.meta.count;row.windowStart=response.meta.responseStart;row.windowEnd=response.meta.responseEnd;}
        const summaryDigest=digest(response.debug?Object.fromEntries(Object.entries(response).filter(([k])=>k!=="debug")):response);
        assert(summaryDigest.length===64);
        tab.checkRequest(controller.signal,deadline);
        row.clientSeconds=(performance.now()-(deadline-tab.XXM_TIMEOUT_MS))/1000;
        assert(row.httpSeconds<=4);assert(row.clientSeconds<5);
      } else {
        const values=Array.isArray(result.bars)?result.bars:Array.isArray(result.items)?result.items:[];
        row.responseRows=values.length;
        row.windowStart=values[0]?.tradeTime??values[0]?.tradeDate??null;
        row.windowEnd=values.at(-1)?.tradeTime??values.at(-1)?.tradeDate??null;
        row.computedThrough=row.windowEnd;
      }
      row.terminal="success";
      return result;
    } catch(error){
      const row=requests.get(owner.requestId);if(row) row.terminal=controller.signal.aborted?"cancelled":"error";
      controller.abort(); throw error;
    }
  });
}
const privateCalls=[];
async function control(name){
  privateCalls.push(name);
  const response=await nativeFetch(`${base}/__audit__/${name}`,{signal:controller.signal});
  assert(response.ok);const value=await response.json();assert.equal(value.groupId,group.groupId);return value;
}
async function runTab(tab,tabId,auditContext){
  const period=group.period,minute=period!=="day",freq=minute?Number(period.slice(1)):null;
  const endDate=group.requestedAsOf??auditContext.businessDate;
  const asOf=group.requestedAsOf?(minute?`${group.requestedAsOf}T15:00:00+08:00`:group.requestedAsOf):undefined;
  const debug=group.mode==="debug"?1:undefined;
  const forecast=round=>execute(tab,tabId,round,()=>tab.fetchForecast("000001.SH",period,asOf,controller.signal,
    {debug,decodeDebug:tab.decodeForecastDebug}),{r4:true});
  const kline=round=>execute(tab,tabId,round,()=>minute?
    tab.fetchIndexDetailMinutes({tsCode:"000001.SH",freq,endDate,limit:500},{signal:controller.signal}):
    tab.indexDetailRequests.run("chart",()=>tab.fetchIndexDetailKline({tsCode:"000001.SH",period:"day",endDate,
      limit:tab.INDEX_DAILY_HISTORY_LIMIT},{signal:controller.signal}),controller.signal));
  const indicators=round=>execute(tab,tabId,round,()=>tab.fetchIndexDetailMinuteIndicators({tsCode:"000001.SH",freq,endDate,limit:500},{signal:controller.signal}));
  if(group.scenario==="forecast_series" || group.scenario==="kline_series" || group.scenario==="indicator_series"){
    for(let round=1;round<=group.samples;round++){
      controller.signal.throwIfAborted();
      if(group.scenario==="forecast_series")await forecast(round);
      else if(group.scenario==="kline_series")await kline(round);
      else await indicators(round);
    }
    return;
  }
  // Each task is enqueued in the same round. Original scheduler priorities win.
  const prediction=forecast(1);
  const nine=execute(tab,tabId,1,()=>tab.loadIndexNineTurnSeries({subjectType:"index",tsCode:"000001.SH",
    period:minute?String(freq):"day",endDate,limit:minute?500:tab.INDEX_DAILY_HISTORY_LIMIT},{signal:controller.signal}));
  const chartPromise=minute?Promise.all([kline(1),indicators(1)]):kline(1);
  const layer=(async()=>{
    const chart=await chartPromise;
    controller.signal.throwIfAborted();
    const model=minute?tab.buildIndexMinuteChartViewModel(chart[0],chart[1]):null;
    const points=model?model.points:chart.bars.map(b=>({time:b.tradeDate,fullDate:b.tradeDate,close:b.close,
      dif:b.factors?.macd?.dif,dea:b.factors?.macd?.dea,macd:b.factors?.macd?.macd}));
    assert(points.length>0);
    let previous="";
    for(const p of points){assert(p.fullDate>previous && [p.close,p.dif,p.dea,p.macd].every(Number.isFinite));previous=p.fullDate;}
    return execute(tab,tabId,1,()=>tab.fetchXxm({tsCode:"000001.SH",period,startDate:points[0].fullDate.slice(0,10),
      endDate:points.at(-1).fullDate.slice(0,10),limit:points.length,debug,decodeDebug:tab.decodeXxmDebug},controller.signal),
      {r4:true,adapt:(response,check)=>tab.buildXxmViewModel(response,points,period,"000001.SH",model?.indicatorVersion??null,check)});
  })();
  const settled=await Promise.allSettled([prediction,nine,layer]);
  const bad=settled.find(x=>x.status==="rejected");if(bad)throw bad.reason;
}
try {
  const auditContext=await control("context");await control("reset");
  const settled=await Promise.allSettled(tabs.map((tab,i)=>runTab(tab,i+1,auditContext)));
  const error=settled.find(value=>value.status==="rejected");if(error)throw error.reason;
  const metrics=await control("metrics");
  assert.deepEqual(privateCalls,["context","reset","metrics"]);
  assert.equal(metrics.requests.length,requests.size);
  for(const row of metrics.requests){
    const client=requests.get(row.requestId);assert(client);assert.equal(row.httpStatus,client.httpStatus);assert.equal(row.bodyBytes,client.bodyBytes);
    assert(client.httpSeconds!==null && client.terminal==="success");
    // Preserve all server facts. Merge only the fields observed by this client.
    row.httpSeconds=client.httpSeconds;row.clientSeconds=client.clientSeconds;
    if(!["signals","forecast"].includes(row.endpointKind)){
      row.computedThrough=client.computedThrough;row.responseRows=client.responseRows;row.windowStart=client.windowStart;row.windowEnd=client.windowEnd;
    }
    row.terminal=row.terminal==="success"?client.terminal:"error";
  }
  metrics.context=auditContext;metrics.privateRequests=privateCalls.length;
  const output=JSON.stringify(metrics);assert(Buffer.byteLength(output)<=1024*1024);
  process.stdout.write(output);
} catch(error){
  controller.abort();
  for(const row of requests.values()) if(row.terminal===null) row.terminal="cancelled";
  // No response/exception text or credentials on stdout/stderr.
  process.stderr.write(JSON.stringify({stage:"client",errorType:error?.constructor?.name??"Error",sentRequests:requests.size,requests:[...requests.values()]}));
  process.exitCode=1;
}
