import { useState } from "react";

import { useEtfActivity } from "../../features/wealth-exploration/etf-activity/model/useEtfActivity";
import { EtfActivityChart } from "../../features/wealth-exploration/etf-activity/ui/EtfActivityChart";
import { EtfActivityRanking } from "../../features/wealth-exploration/etf-activity/ui/EtfActivityRanking";
import { Panel } from "../../shared/ui/Panel";
import { RangeSwitch } from "../../shared/ui/RangeSwitch";
import { WealthExplorationShell } from "./layout/WealthExplorationShell";
import "../../features/wealth-exploration/etf-activity/ui/etf-activity.css";
import "./wealth-exploration-page.css";

const RANGES = [{ value: "1m", label: "1 个月" }, { value: "3m", label: "3 个月" }];

export function EtfActivityPage() {
  const { data, pending, error, retry } = useEtfActivity();
  const [range, setRange] = useState("1m");
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const start = range === "1m" ? data?.oneMonthStartDate : null;
  const points = start ? data?.trend.filter((point) => point.tradeDate >= start) : data?.trend;
  const hasTrend = Boolean(points?.length);

  return (
    <WealthExplorationShell activeShortcutKey="etf-activity" currentPageLabel="ETF 动态" showMarketContext={false}>
      {() => (
        <div className="etf-activity-workspace">
          <Panel title="ETF 日成交额趋势" className="etf-activity-panel etf-trend-panel"
            meta={hasTrend ? <RangeSwitch value={range} options={RANGES} onChange={setRange} ariaLabel="ETF 趋势区间" /> : undefined}>
            {(hasTrend || pending) && <div className="etf-trend-caption">沪深场内 ETF · 亿元</div>}
            {points?.length ? (
              <EtfActivityChart points={points} selectedDate={selectedDate} onSelectDate={setSelectedDate} />
            ) : (
              <div className="etf-state" role={error ? "alert" : "status"}>
                {error ?? (pending ? "正在读取 ETF 日成交额…" : "暂无可用的 ETF 日线数据")}
                {error && <button className="tab-btn" type="button" onClick={retry}>重试</button>}
              </div>
            )}
          </Panel>
          <EtfActivityRanking data={data} pending={pending} failed={error !== null} onRetry={retry} />
        </div>
      )}
    </WealthExplorationShell>
  );
}
