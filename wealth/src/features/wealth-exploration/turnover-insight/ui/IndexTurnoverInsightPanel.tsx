import type { IndexTurnoverInsightPanelViewModel } from "../model/indexTurnoverInsightTypes";
import type { TurnoverInsightViewState } from "../model/turnoverInsightTypes";
import { TurnoverInsightPanel } from "./TurnoverInsightPanel";

interface IndexTurnoverInsightPanelProps {
  asOf: string | null;
  model: IndexTurnoverInsightPanelViewModel;
  onRetry: () => void;
}

export function IndexTurnoverInsightPanel({ asOf, model, onRetry }: IndexTurnoverInsightPanelProps) {
  const viewState = model.status.toLowerCase() as TurnoverInsightViewState;
  const titleId = `index-turnover-insight-${model.tsCode.replace(".", "-")}`;
  return (
    <article className="index-turnover-insight-card" aria-labelledby={titleId}>
      <header className="index-turnover-insight-card__header">
        <div className="index-turnover-insight-card__identity">
          <h3 id={titleId}>{model.indexName}成交额</h3>
          <span className="index-turnover-insight-card__code num">{model.tsCode}</span>
          <small>当日与昨日同分钟累计</small>
        </div>
        {asOf ? <span className="index-turnover-insight-card__asof num">{asOf}</span> : null}
      </header>
      <TurnoverInsightPanel
        emptyTitle={`${model.indexName}暂无成交额数据`}
        errorTitle={`${model.indexName}成交额加载失败`}
        layout="compact"
        model={model}
        onRetry={onRetry}
        viewState={viewState}
      />
    </article>
  );
}
