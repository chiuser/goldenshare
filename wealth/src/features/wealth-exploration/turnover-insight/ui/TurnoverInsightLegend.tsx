export function TurnoverInsightLegend() {
  return (
    <div className="turnover-insight-legend" aria-label="成交额曲线图例">
      <span><i className="turnover-insight-legend__line turnover-insight-legend__line--current" />当日累计</span>
      <span><i className="turnover-insight-legend__line turnover-insight-legend__line--previous" />昨日累计</span>
      <span><i className="turnover-insight-legend__line turnover-insight-legend__line--avg5d" />5日均值</span>
      <span><i className="turnover-insight-legend__line turnover-insight-legend__line--avg20d" />20日均值</span>
    </div>
  );
}
