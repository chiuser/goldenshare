import { useState } from "react";

import { Panel } from "../../../../shared/ui/Panel";
import { RangeSwitch } from "../../../../shared/ui/RangeSwitch";
import { EtfTurnoverPlot } from "../../etf-activity/ui/EtfTurnoverPlot";
import type { MajorEtfMonitorState } from "../model/useMajorEtfMonitor";

const RANGES = [{ value: "1m", label: "1 个月" }, { value: "3m", label: "3 个月" }];
const SERIES = [{ field: "amountYuan", label: "合计成交额", color: "amount" }] as const;

export function MajorEtfTurnoverChart({ state }: { state: MajorEtfMonitorState }) {
  const [range, setRange] = useState("1m");
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const { data, status } = state;
  const trend = data?.trend ?? [];
  const start = data?.oneMonthStartDate;
  const points = range === "1m" && start ? trend.filter(({ tradeDate }) => tradeDate >= start) : trend;
  const hasAnyTrend = trend.some(({ amountYuan }) => amountYuan !== null);
  const hasVisibleTrend = points.some(({ amountYuan }) => amountYuan !== null);
  const failed = status === "error" || status === "timeout";
  let message = "暂无可用的主要ETF成交额数据";
  if (status === "loading") message = "正在读取主要ETF成交额…";
  if (failed) message = "主要ETF成交额趋势暂不可读取";

  function changeRange(next: string) {
    setRange(next);
    if (next === "1m" && start && selectedDate && selectedDate < start) setSelectedDate(null);
  }

  return (
    <Panel title="主要ETF（国家队）成交额趋势" className="etf-activity-panel etf-trend-panel major-etf-trend"
      meta={(
        <fieldset className="major-etf-ranges" disabled={!hasAnyTrend}>
          <RangeSwitch value={range} options={RANGES} onChange={changeRange} ariaLabel="主要ETF 趋势区间" />
        </fieldset>
      )}>
      <div className="etf-trend-caption">14 只 ETF · 亿元</div>
      {hasVisibleTrend ? (
        <EtfTurnoverPlot key={range} points={points} selectedDate={selectedDate} onSelectDate={setSelectedDate}
          series={SERIES} turnoverUnit=" 亿元" ariaLabel="主要ETF 成交额趋势图，使用左右方向键选择交易日" />
      ) : (
        <div className="etf-state" role={failed ? undefined : "status"}>{message}</div>
      )}
    </Panel>
  );
}
