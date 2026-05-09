import { DataStatusBadge } from "../../../shared/ui/DataStatusBadge";
import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type { FactItem } from "../api/marketOverviewTypes";

interface MarketSummaryPanelProps {
  viewState: "loading" | "ready" | "error";
  facts?: FactItem[];
  textTitle?: string;
  textContent?: string;
  statusLabel?: string;
  statusTone?: "ready" | "delayed";
  layoutVariant?: "FIVE_SINGLE_ROW" | "SIX_TWO_ROWS";
  errorMessage?: string;
}

export function MarketSummaryPanel({
  viewState,
  facts,
  textTitle,
  textContent,
  statusLabel,
  statusTone,
  layoutVariant,
  errorMessage,
}: MarketSummaryPanelProps) {
  const badgeLabel = viewState === "loading" ? "客观总结加载中" : viewState === "error" ? "客观总结加载失败" : statusLabel ?? "事实聚合已就绪";
  const badgeTone = viewState === "ready" ? (statusTone ?? "ready") : "delayed";

  return (
    <section className="summary-panel" aria-label="今日市场客观总结">
      <div className="section-header">
        <div className="section-title">
          今日市场客观总结
          <span
            className="help"
            data-tip="基于主要指数、涨跌家数、成交额、资金流、涨跌停事实生成；不包含买卖建议、仓位建议或明日预测。"
            title="基于主要指数、涨跌家数、成交额、资金流、涨跌停事实生成；不包含买卖建议、仓位建议或明日预测。"
          >
            ?
          </span>
        </div>
        <DataStatusBadge label={badgeLabel} tone={badgeTone} />
      </div>
      {viewState === "loading" ? (
        <div className="summary-state-wrap">
          <SkeletonBlock />
        </div>
      ) : null}
      {viewState === "error" ? (
        <div className="summary-state-wrap">
          <div className="state-block error-box">
            <strong>error</strong>
            <br />
            <span>{errorMessage ?? "请求超时，请稍后重试。"}</span>
          </div>
        </div>
      ) : null}
      {viewState === "ready" ? (
        <div className="summary-body-v2">
          <div className={layoutVariant === "SIX_TWO_ROWS" ? "summary-facts-v2 six" : "summary-facts-v2"}>
            {(facts ?? []).map((fact) => (
              <div className="fact-card" key={fact.label}>
                <div className="fact-label">{fact.label}</div>
                <div className={fact.valueTone ? `fact-value ${fact.valueTone}` : "fact-value"}>{renderFactValue(fact.label, fact.value)}</div>
                <div className="fact-sub">{fact.sub}</div>
              </div>
            ))}
          </div>
          <div className="summary-text-card">
            <strong>{textTitle}</strong>
            {textContent}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function renderFactValue(label: string, value: string) {
  if (label.includes("主要指数涨跌比") && value.includes(":")) {
    const [left, right] = value.split(":").map((item) => item.trim());
    return (
      <>
        <span className="up">{left}</span>
        <span className="secondary">:</span>
        <span className="down">{right}</span>
      </>
    );
  }

  if (label.includes("/") && value.includes("/")) {
    const [left, right] = value.split("/").map((item) => item.trim());
    return (
      <>
        <span className="up">{left}</span>
        <span className="secondary">/</span>
        <span className="down">{right}</span>
      </>
    );
  }

  return value;
}
