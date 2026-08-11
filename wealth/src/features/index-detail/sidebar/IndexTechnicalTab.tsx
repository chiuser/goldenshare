import type { IndexDetailViewModel, TrendChannelViewModel } from "../model/indexDetailTypes";

export function IndexTechnicalTab({ trend, viewModel }: { trend: TrendChannelViewModel | null; viewModel: IndexDetailViewModel }) {
  const latest = trend?.points.at(-1) ?? null;
  return (
    <section className="index-technical-module" aria-label="技术面">
      <div className="index-tab-section-title"><strong>技术面</strong><span>{viewModel.asOfTradeDate}</span></div>
      <TechnicalCard title="技术结论" value="--" note="后续由独立策略 API 提供" />
      <TechnicalCard title="九转序列" value="--" note="后续由独立 API 提供" />
      <div className="index-technical-card">
        <div><strong>趋势通道</strong><span>{viewModel.capabilities.supportsTrendChannel ? "上证指数 · 日线" : "当前指数不支持"}</span></div>
        <div className="index-technical-grid">
          <Metric label="短期上轨" value={format(latest?.shortUpper)} />
          <Metric label="短期下轨" value={format(latest?.shortLower)} />
          <Metric label="长期上轨" value={format(latest?.longUpper)} />
          <Metric label="长期下轨" value={format(latest?.longLower)} />
        </div>
      </div>
    </section>
  );
}

function TechnicalCard({ title, value, note }: { title: string; value: string; note: string }) {
  return <div className="index-technical-card"><div><strong>{title}</strong><span>{note}</span></div><b className="index-technical-value">{value}</b></div>;
}
function Metric({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><b>{value}</b></div>; }
function format(value: number | undefined): string { return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "--"; }
