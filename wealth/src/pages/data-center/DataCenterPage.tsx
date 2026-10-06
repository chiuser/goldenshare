import { dataCenterApi } from "../../features/data-center/api/dataCenterApi";
import { useObserver } from "../../features/data-center/model/useObserver";
import { Button, Empty, Notice } from "../../features/data-center/ui/primitives";
import { navigateWealth } from "../../app/routes/routerState";
import { DataCenterShell } from "./DataCenterShell";
const readModules = (s: AbortSignal) => dataCenterApi.modules(s);
export function DataCenterPage() {
  const state = useObserver(readModules);
  return <DataCenterShell>{state.error ? <Notice>{state.error}<Button onClick={state.refresh}>重新读取</Button></Notice> : !state.value ? <Empty title="正在读取数据模块…" /> : state.value.modules.length ? <div className="dc-modules">{state.value.modules.map(card => <button className="dc-module-card" type="button" key={card.moduleKey} onClick={() => navigateWealth(card.path)}>
    <span><strong>{card.title}</strong><span className="dc-badge num">{card.badge}</span></span><small>{card.moduleKey === "announcements" ? "查询公司公告，管理 PDF 下载与归档。" : card.description}</small></button>)}</div> : <section className="dc-home-empty"><strong>当前暂无可用数据模块</strong><p>可用模块会在此展示。</p></section>}</DataCenterShell>;
}
