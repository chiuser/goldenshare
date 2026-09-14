import { useState, type ReactNode } from "react";
import type { PositionRow, StockRef } from "../api/generatedContracts";
import { usePositions } from "../model/usePositions";
import { PositionsSummary } from "./PositionsSummary";
import { PositionsTable } from "./PositionsTable";
import { PositionsCharts, type GraphicView } from "./PositionsCharts";
import { PositionDetailDialog } from "./PositionDetailDialog";
import { TradingAssistantAction } from "./TradingAssistantForm";
import { HoldingAnalysisPanel } from "./HoldingAnalysisPanel";
import "./positions.css";

export function PositionsWorkspace({ selected, revision, onSell, actions, analysis, onAnalysisChange }: { selected: string; revision: number; actions: ReactNode; analysis: boolean; onAnalysisChange: (value: boolean) => void; onSell: (account: string, stock: StockRef) => void }) {
  const read = usePositions(selected, revision);
  const [view, setView] = useState<"list" | GraphicView>("list");
  const [detail, setDetail] = useState<{ row: PositionRow; token: string } | null>(null);
  const data = read.data;
  return <section className="ta-positions" aria-label="持仓股">
    {read.error && <div className="ta-position-read-error" role="alert">持仓信息暂时无法读取，自动检查已停止。<TradingAssistantAction onClick={read.refresh}>重新读取</TradingAssistantAction></div>}
    {read.loading && <div className="ta-page-status" role="status">正在读取持仓…</div>}
    {data && <>
      {analysis ? <HoldingAnalysisPanel selected={selected} parent={data} onReturn={() => onAnalysisChange(false)} onRefresh={read.refresh} /> : <>
      <PositionsSummary summary={data.summary} graphical={view !== "list"} />
      <div className="ta-position-toolbar"><div className="ta-segments" role="group" aria-label="持仓视图">{([['list', '列表'], ['bar', '条形图'], ['pie', '饼图'], ['map', '盈亏地图']] as const).map(([key, label]) => <button type="button" key={key} aria-pressed={view === key} onClick={() => setView(key)}>{label}</button>)}</div><TradingAssistantAction onClick={() => onAnalysisChange(true)}>持仓分析</TradingAssistantAction>{actions}<TradingAssistantAction onClick={read.refresh}>重新读取</TradingAssistantAction></div>
      {data.coverage.dataStatus !== "Ready" && data.coverage.dataStatus !== "Empty" && <div className="ta-position-coverage" role="status">
        {data.coverage.reason ?? ({ Delayed: "等待有效估值数据", Partial: "部分数据尚未就绪", Recalculating: "正在重新计算", Error: "核算结果暂不可用" }[data.coverage.dataStatus])}
        {data.coverage.accounts.filter(account => account.reason).map(account => <p key={account.accountId}>{data.scope.accounts.find(ref => ref.accountId === account.accountId)?.name}：{account.reason}</p>)}
      </div>}
      {view === "list" ? <PositionsTable rows={data.items} onDetail={row => setDetail({ row, token: data.readContext.contextToken })} />
        : <PositionsCharts data={data} view={view} onDetail={row => setDetail({ row, token: data.readContext.contextToken })} />}
      {detail && detail.token === data.readContext.contextToken && <PositionDetailDialog selected={selected} row={detail.row} token={detail.token} onClose={() => setDetail(null)} onRefresh={read.refresh}
        onSell={(account, stock) => { setDetail(null); onSell(account, stock); }} />}
      </>}
    </>}
    {!data && actions}
  </section>;
}
