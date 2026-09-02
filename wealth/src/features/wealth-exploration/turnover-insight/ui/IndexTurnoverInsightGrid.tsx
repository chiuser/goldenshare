import type { IndexTurnoverInsightControllerResult } from "../model/indexTurnoverInsightTypes";
import { IndexTurnoverInsightPanel } from "./IndexTurnoverInsightPanel";
import { TurnoverInsightPanel } from "./TurnoverInsightPanel";

interface IndexTurnoverInsightGridProps {
  controller: IndexTurnoverInsightControllerResult;
}

export function IndexTurnoverInsightGrid({ controller }: IndexTurnoverInsightGridProps) {
  if (controller.capabilityState === "unsupported") return null;
  const asOf = controller.model?.asOf;
  return (
    <section className="index-turnover-insight-section" aria-labelledby="index-turnover-insight-title">
      <header className="index-turnover-insight-header">
        <div>
          <h2 id="index-turnover-insight-title">主要指数成交额</h2>
          <p>十个主要指数当日与上一交易日一分钟累计成交额对比</p>
        </div>
      </header>
      {controller.model?.message ? (
        <p className={`index-turnover-insight-group-notice index-turnover-insight-group-notice--${controller.viewState}`}>
          {controller.model.message}
        </p>
      ) : null}
      {controller.model ? (
        <div className="index-turnover-insight-grid">
          {controller.model.indices.map((item) => (
            <IndexTurnoverInsightPanel
              asOf={asOf ?? null}
              key={item.tsCode}
              model={item}
              onRetry={controller.retry}
            />
          ))}
        </div>
      ) : controller.viewState === "loading" ? (
        <div className="index-turnover-insight-grid" aria-label="主要指数成交额加载中">
          {Array.from({ length: 10 }, (_, index) => (
            <article className="index-turnover-insight-card" key={index}>
              <header className="index-turnover-insight-card__header index-turnover-insight-card__header--loading" />
              <TurnoverInsightPanel
                layout="compact"
                loadingLabel={`指数成交额卡片 ${index + 1} 加载中`}
                model={null}
                onRetry={controller.retry}
                viewState="loading"
              />
            </article>
          ))}
        </div>
      ) : (
        <div className="index-turnover-insight-group-state">
          <strong>主要指数成交额加载失败</strong>
          <span>{controller.errorMessage ?? "请稍后重试。"}</span>
          <button type="button" onClick={controller.retry}>重试</button>
        </div>
      )}
    </section>
  );
}
