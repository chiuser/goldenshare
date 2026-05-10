import { useEffect, useState } from "react";
import { formatPoint, formatSignedPercent } from "../../../shared/lib/formatters";
import { directionClass, directionFromNumber } from "../../../shared/lib/marketDirection";
import { DataStatusBadge } from "../../../shared/ui/DataStatusBadge";
import { Panel } from "../../../shared/ui/Panel";
import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type { MarketLeaderboardsViewModel } from "./api/marketLeaderboardsAdapter";

interface LeaderboardPanelProps {
  viewState: "loading" | "ready" | "error";
  leaderboards?: MarketLeaderboardsViewModel;
  errorMessage?: string;
  onAction: (message: string) => void;
}

export function LeaderboardPanel({ viewState, leaderboards, errorMessage, onAction }: LeaderboardPanelProps) {
  const tabs = leaderboards?.tabs ?? [];
  const [activeKey, setActiveKey] = useState(tabs[0]?.key ?? "");
  useEffect(() => {
    if (!tabs.length) {
      setActiveKey("");
      return;
    }
    if (!tabs.some((tab) => tab.key === activeKey)) {
      setActiveKey(tabs[0].key);
    }
  }, [activeKey, tabs]);

  const active = tabs.find((tab) => tab.key === activeKey) ?? tabs[0];
  const badgeLabel = viewState === "loading" ? "榜单加载中" : viewState === "error" ? "榜单加载失败" : leaderboards?.statusLabel ?? "事实聚合已就绪";
  const badgeTone = viewState === "ready" ? (leaderboards?.statusTone ?? "ready") : "delayed";

  return (
    <Panel
      className="leaderboard"
      title="榜单速览"
      help="展示个股涨幅、跌幅、成交额、换手、量比、人气和飙升榜。行 hover 清晰，点击进入个股详情；红涨绿跌正确。"
      meta={<DataStatusBadge label={badgeLabel} tone={badgeTone} />}
    >
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
        <>
          <div className="tabs">
            {tabs.map((tab) => (
              <button className={tab.key === active?.key ? "tab-btn active" : "tab-btn"} key={tab.key} type="button" onClick={() => setActiveKey(tab.key)}>
                {tab.label}
              </button>
            ))}
          </div>
          <table aria-label="个股榜单">
            <thead>
              <tr>
                <th>排名</th>
                <th>股票</th>
                <th>最新价</th>
                <th>涨跌幅</th>
                <th>换手率</th>
                <th>量比</th>
                <th>成交量</th>
                <th>成交额</th>
              </tr>
            </thead>
            <tbody>
              {(active?.rows ?? []).map((row) => (
                <LeaderboardTableRow key={`${active?.key}-${row.code}-${row.rank}`} onAction={onAction} row={row} />
              ))}
            </tbody>
          </table>
        </>
      ) : null}
    </Panel>
  );
}

function LeaderboardTableRow({
  row,
  onAction,
}: {
  row: MarketLeaderboardsViewModel["tabs"][number]["rows"][number];
  onAction: (message: string) => void;
}) {
  const cls = directionClass(directionFromNumber(row.changePct));
  return (
    <tr onClick={() => onAction(`进入个股详情：${row.code}`)}>
      <td className="num muted">{row.rank}</td>
      <td className="stock-cell">
        <strong>{row.name}</strong>
        <br />
        <span className="muted num">{row.code}</span>
      </td>
      <td className={`num ${cls}`}>{row.latestPrice === null ? "--" : formatPoint(row.latestPrice)}</td>
      <td className={`num ${cls}`}>{row.changePct === null ? "--" : formatSignedPercent(row.changePct)}</td>
      <td className="num secondary">{row.turnoverRate === null ? "--" : `${row.turnoverRate.toFixed(1)}%`}</td>
      <td className="num secondary">{row.volumeRatio === null ? "--" : row.volumeRatio.toFixed(1)}</td>
      <td className="num secondary">{row.volumeText}</td>
      <td className="num secondary">{row.amountText}</td>
    </tr>
  );
}

