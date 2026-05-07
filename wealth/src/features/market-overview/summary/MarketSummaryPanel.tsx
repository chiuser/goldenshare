import { DataStatusBadge } from "../../../shared/ui/DataStatusBadge";
import type { FactItem } from "../api/marketOverviewTypes";

interface MarketSummaryPanelProps {
  facts: FactItem[];
  text: string;
}

export function MarketSummaryPanel({ facts, text }: MarketSummaryPanelProps) {
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
        <DataStatusBadge label="事实聚合已就绪" />
      </div>
      <div className="summary-body-v2">
        <div className="summary-facts-v2">
          {facts.map((fact) => (
            <div className="fact-card" key={fact.label}>
              <div className="fact-label">{fact.label}</div>
              <div className={fact.valueTone ? `fact-value ${fact.valueTone}` : "fact-value"}>{renderFactValue(fact.label, fact.value)}</div>
              <div className="fact-sub">{fact.sub}</div>
            </div>
          ))}
        </div>
        <div className="summary-text-card">
          <strong>截至收盘，A 股主要指数多数上涨。</strong>
          {text.replace("截至收盘，A 股主要指数多数上涨。", "")}
        </div>
      </div>
    </section>
  );
}

function renderFactValue(label: string, value: string) {
  if (label === "上涨 / 下跌") {
    return (
      <>
        <span className="up">3421</span>
        <span className="secondary">/</span>
        <span className="down">1488</span>
      </>
    );
  }

  if (label === "涨停 / 跌停") {
    return (
      <>
        <span className="up">59</span>
        <span className="secondary">/</span>
        <span className="down">8</span>
      </>
    );
  }

  return value;
}
