import type {
  TurnoverInsightViewModel,
  TurnoverInsightViewState,
} from "../model/turnoverInsightTypes";
import { TurnoverInsightPanel } from "./TurnoverInsightPanel";
import "./turnover-insight.css";

interface TurnoverInsightSectionProps {
  viewState: TurnoverInsightViewState;
  model: TurnoverInsightViewModel | null;
  errorMessage?: string;
  onRetry: () => void;
}

export function TurnoverInsightSection({
  viewState,
  model,
  errorMessage,
  onRetry,
}: TurnoverInsightSectionProps) {
  return (
    <section className="turnover-insight-section" aria-labelledby="turnover-insight-title">
      <header className="turnover-insight-header">
        <div>
          <h1 id="turnover-insight-title">成交额洞察</h1>
          <p>当日与上一交易日全市场一分钟累计成交额对比</p>
        </div>
        {model?.asOf ? (
          <span className="turnover-insight-asof num">截至 {formatAsOf(model.asOf)}</span>
        ) : null}
      </header>
      <TurnoverInsightPanel
        errorMessage={errorMessage}
        layout="full"
        model={model}
        onRetry={onRetry}
        viewState={viewState}
      />
    </section>
  );
}

function formatAsOf(value: string): string {
  const match = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  return match ? `${match[1]} ${match[2]}` : value;
}
