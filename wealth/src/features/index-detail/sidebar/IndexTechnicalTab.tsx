import type { NineTurnPeriod } from "../../nine-turn/api/nineTurnApiTypes";
import type { NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
import type { IndexDetailViewModel, TrendChannelViewModel } from "../model/indexDetailTypes";
import { INDEX_TECHNICAL_NINE_TURN_PERIODS, type IndexTechnicalNineTurnSummary } from "../model/indexTechnicalNineTurnSummary";
import { IndexDetailModuleState } from "../state/IndexDetailModuleState";

interface IndexTechnicalTabProps {
  nineTurnSummary: IndexTechnicalNineTurnSummary;
  onNineTurnRetry: (period: NineTurnPeriod) => void;
  onTrendRetry: () => void;
  trend: TrendChannelViewModel | null;
  trendPhase: "unavailable" | "loading" | "ready" | "error";
  viewModel: IndexDetailViewModel;
}

export function IndexTechnicalTab({ nineTurnSummary, onNineTurnRetry, onTrendRetry, trend, trendPhase, viewModel }: IndexTechnicalTabProps) {
  const latest = trend?.points.at(-1) ?? null;
  return (
    <section className="index-technical-module" aria-label="技术面">
      <div className="index-tab-section-title"><strong>技术面</strong><span>{viewModel.asOfTradeDate ?? "--"}</span></div>
      <TechnicalCard title="技术结论" value="--" note="后续由独立策略 API 提供" />
      <NineTurnSummaryCard layers={nineTurnSummary} onRetry={onNineTurnRetry} />
      <div className="index-technical-card">
        <div><strong>趋势通道</strong><span>{viewModel.capabilities.supportsTrendChannel ? "上证指数 · 日线" : "当前指数不支持"}</span></div>
        {viewModel.capabilities.supportsTrendChannel && trendPhase === "loading" ? <IndexDetailModuleState text="正在加载趋势通道…" /> : null}
        {viewModel.capabilities.supportsTrendChannel && trendPhase === "error" ? <IndexDetailModuleState actionLabel="重试" onAction={onTrendRetry} text="趋势通道加载失败" tone="error" /> : null}
        {trendPhase !== "loading" && trendPhase !== "error" ? <div className="index-technical-grid">
          <Metric label="短期上轨" value={format(latest?.shortUpper)} />
          <Metric label="短期下轨" value={format(latest?.shortLower)} />
          <Metric label="长期上轨" value={format(latest?.longUpper)} />
          <Metric label="长期下轨" value={format(latest?.longLower)} />
        </div> : null}
      </div>
    </section>
  );
}

function NineTurnSummaryCard({
  layers,
  onRetry,
}: {
  layers: IndexTechnicalNineTurnSummary;
  onRetry: (period: NineTurnPeriod) => void;
}) {
  return (
    <div aria-label="九转序列摘要" className="index-technical-card index-nine-turn-summary">
      <div><strong>九转序列</strong><span>客观序列 · 非交易信号</span></div>
      <div className="index-nine-turn-summary-rows">
        {INDEX_TECHNICAL_NINE_TURN_PERIODS.map(({ label, period }) => {
          const layer = layers[period];
          const latest = layer.data?.latestMarker ?? null;
          const value = latest ? `${latest.direction === "UP" ? "上序" : "下序"} ${latest.sequenceNumber}` : "--";
          return (
            <div className="index-nine-turn-summary-row" data-phase={layer.phase} key={period}>
              <span>{label}</span>
              <b className={latest?.direction === "UP" ? "up" : latest?.direction === "DOWN" ? "down" : "secondary"}>{value}</b>
              <small>{nineTurnStatusText(layer)}</small>
              {layer.canRetry ? <button aria-label={`重试${label}九转`} onClick={() => onRetry(period)} type="button">重试</button> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function nineTurnStatusText(layer: NineTurnLayerViewModel): string {
  if (layer.phase === "LOADING") return "加载中";
  if (layer.phase === "EMPTY") return "暂时空缺";
  if (layer.phase === "SOURCE_EMPTY") return "数据源未覆盖";
  if (layer.phase === "PARTIAL") return "部分缺失";
  if (layer.phase === "ERROR") return "加载失败";
  if (layer.phase === "FORBIDDEN") return "权限不足";
  if (layer.phase === "UNSUPPORTED") return "当前环境未开放";
  if (layer.phase === "IDLE") return "等待加载";
  return layer.data?.latestMarker ? "最新标记" : "暂时空缺";
}

function TechnicalCard({ title, value, note }: { title: string; value: string; note: string }) {
  return <div className="index-technical-card"><div><strong>{title}</strong><span>{note}</span></div><b className="index-technical-value">{value}</b></div>;
}
function Metric({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><b>{value}</b></div>; }
function format(value: number | undefined): string { return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "--"; }
