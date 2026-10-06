import { useCallback, useEffect } from "react";
import { navigateWealth } from "../../app/routes/routerState";
import { dataCenterApi } from "../../features/data-center/api/dataCenterApi";
import { useObserver } from "../../features/data-center/model/useObserver";
import { DownloadPanel } from "../../features/data-center/ui/DownloadPanel";
import { QueryPanel } from "../../features/data-center/ui/QueryPanel";
import { Button, Empty, Notice } from "../../features/data-center/ui/primitives";
import { DataCenterShell } from "./DataCenterShell";
const readContext = (s: AbortSignal) => dataCenterApi.context(s);
export const ANNOUNCEMENTS_PATH = "/wealth/data-center/announcements";
export function readAnnouncementRoute(search: string) {
  const params = new URLSearchParams(search); const raw = params.get("tab");
  return { tab: raw === "downloads" ? "downloads" : "query", runId: params.get("runId"), invalidTab: raw !== null && raw !== "query" && raw !== "downloads" };
}
export function AnnouncementsPage({ search = "" }: { search?: string }) {
  const state = useObserver(readContext); const route = readAnnouncementRoute(search);
  const navigate = useCallback((tab: string, runId: string | null) => { const params = new URLSearchParams({ tab }); if (runId) params.set("runId", runId); navigateWealth(`${ANNOUNCEMENTS_PATH}?${params}`); }, []);
  useEffect(() => { if (route.invalidTab) navigateWealth(`${ANNOUNCEMENTS_PATH}?tab=query`, { replace: true }); }, [route.invalidTab]);
  const c = state.value;
  return <DataCenterShell announcement>
    <div className="dc-title"><div><h1>上市公司公告</h1><p>本地公告查询与 PDF 下载归档</p></div><span className="dc-badge dc-info">本地数据</span><span className={`dc-badge ${c?.archiveAvailability === "unavailable" ? "dc-danger" : ""}`}>{c ? c.archiveAvailability === "ready" ? "外盘已连接" : "外盘不可用" : "外盘状态待确认"}</span></div>
    <div className="dc-tabs" role="tablist" aria-label="查询与下载管理">{["query", "downloads"].map(tab => <button type="button" role="tab" aria-selected={route.tab === tab} key={tab} className={route.tab === tab ? "active" : ""} onClick={() => navigate(tab, route.runId)}>{tab === "query" ? "公告查询" : "下载管理"}</button>)}</div>
    {state.error && <Notice>{state.error}。{c ? "正在显示最后读取的上下文。" : "当前公告数据与下载状态暂不可确认。"}<Button onClick={state.refresh}>重新读取</Button></Notice>}
    {!c && !state.error && <Empty title="正在读取本地公告能力…" />}
    {c && <>
      {c.sourceAvailability !== "ready" && <Notice>本地公告来源暂不可用。历史任务可读取；网页不会触发 DG 同步。<Button onClick={state.refresh}>重新读取来源</Button></Notice>}
      <div hidden={route.tab !== "query"} role="tabpanel"><QueryPanel context={c} refreshContext={state.refresh} /></div>
      <div hidden={route.tab !== "downloads"} role="tabpanel"><DownloadPanel context={c} enabled={route.tab === "downloads"} routeRunId={route.runId} onSelect={id => navigate("downloads", id)} refreshContext={state.refresh} /></div>
    </>}
  </DataCenterShell>;
}
