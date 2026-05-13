import { directionClass, directionFromNumber } from "../../../shared/lib/marketDirection";
import { formatSignedPercent } from "../../../shared/lib/formatters";
import { Panel } from "../../../shared/ui/Panel";
import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type { SectorOverviewRankRowViewModel, MarketSectorOverviewViewModel } from "./api/marketSectorOverviewAdapter";

interface SectorOverviewPanelProps {
  sectorOverview?: MarketSectorOverviewViewModel | null;
  viewState: "loading" | "ready" | "error";
  errorMessage?: string;
  onAction: (message: string) => void;
}

export function SectorOverviewPanel({ sectorOverview, viewState, errorMessage, onAction }: SectorOverviewPanelProps) {
  return (
    <Panel
      title="板块速览"
      help="Review v2 指定结构：左侧行业/概念/地域/资金流 4 列 × 2 行 Top5 榜单矩阵；右侧板块热力图 5 行 × 4 列并跨两行。点击板块进入板块与榜单行情页。"
      meta={
        <button className="refresh-btn" type="button" onClick={() => onAction("跳转：/market/sector-heatmap")}>
          进入板块热力图
        </button>
      }
    >
      {viewState === "loading" ? <SkeletonBlock /> : null}
      {viewState === "error" ? (
        <div className="state-block error-box">
          <strong>error</strong>
          <br />
          <span>{errorMessage ?? "板块速览加载失败"}</span>
        </div>
      ) : null}
      {viewState === "ready" && sectorOverview ? (
      <div className="sector-v2-layout">
        <div className="sector-matrix">
          {sectorOverview.columns.map((column) => (
            <div className="sector-col" key={column.key}>
              <div className="sector-title">
                <span>{column.title}</span>
                <span className={column.tone}>{column.valueLabel}</span>
              </div>
              {column.rows.map((row, index) => (
                <SectorRankItem key={row.name} onAction={onAction} rank={index + 1} row={row} tone={column.tone} />
              ))}
            </div>
          ))}
        </div>
        <div className="heatmap-panel">
          <div className="sector-title">
            <span>板块热力图</span>
          </div>
          <div className="heatmap-preview">
            {sectorOverview.heatmap.map((cell) => {
              const cls = directionClass(directionFromNumber(cell.pct));
              const alpha = cell.pct >= 0 ? Math.min(0.42, 0.08 + cell.pct / 18) : Math.min(0.42, 0.08 + Math.abs(cell.pct) / 12);
              const bg = cell.pct >= 0 ? `rgba(255,77,90,${alpha})` : `rgba(21,199,132,${alpha})`;

              return (
                <button
                  aria-label={`板块热力图-${cell.name}`}
                  className={`heat-cell ${cls}`}
                  key={cell.name}
                  style={{ background: bg }}
                  title={`${cell.name}｜涨跌幅 ${formatSignedPercent(cell.pct)}｜点击进入板块与榜单行情页`}
                  type="button"
                  onClick={() => onAction(`进入详情：${cell.name}`)}
                >
                  <strong>{cell.name}</strong>
                  <span className={`num ${cls}`}>{formatSignedPercent(cell.pct)}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
      ) : null}
    </Panel>
  );
}

function SectorRankItem({
  row,
  rank,
  tone,
  onAction,
}: {
  row: SectorOverviewRankRowViewModel;
  rank: number;
  tone: "up" | "down";
  onAction: (message: string) => void;
}) {
  return (
    <button className="rank-item" type="button" onClick={() => onAction(`进入详情：${row.name}`)}>
      <span className="num muted">{rank}</span>
      <span>{row.name}</span>
      <span className={`num ${tone}`}>{row.text}</span>
    </button>
  );
}
