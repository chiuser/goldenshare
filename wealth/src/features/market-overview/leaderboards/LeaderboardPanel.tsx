import { useState } from "react";
import { directionFromNumber, directionClass } from "../../../shared/lib/marketDirection";
import { formatPoint, formatSignedPercent } from "../../../shared/lib/formatters";
import { DataStatusBadge } from "../../../shared/ui/DataStatusBadge";
import { Panel } from "../../../shared/ui/Panel";
import type { LeaderboardRow, MarketOverview } from "../api/marketOverviewTypes";

interface LeaderboardPanelProps {
  overview: MarketOverview;
  onAction: (message: string) => void;
}

export function LeaderboardPanel({ overview, onAction }: LeaderboardPanelProps) {
  const [activeKey, setActiveKey] = useState(overview.leaderboards[0]?.key ?? "");
  const active = overview.leaderboards.find((tab) => tab.key === activeKey) ?? overview.leaderboards[0];

  return (
    <Panel
      className="leaderboard"
      title="榜单速览"
      help="展示个股涨幅、跌幅、成交额、换手、量比异动榜。行 hover 清晰，点击进入个股详情；红涨绿跌正确。"
      meta={<DataStatusBadge label="dc_hot + 行情派生" />}
    >
      <div className="tabs">
        {overview.leaderboards.map((tab) => (
          <button className={tab.key === active.key ? "tab-btn active" : "tab-btn"} key={tab.key} type="button" onClick={() => setActiveKey(tab.key)}>
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
          {active.rows.map((row, index) => (
            <LeaderboardTableRow key={row.code} onAction={onAction} rank={index + 1} row={row} />
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function LeaderboardTableRow({ row, rank, onAction }: { row: LeaderboardRow; rank: number; onAction: (message: string) => void }) {
  const cls = directionClass(directionFromNumber(row.changePct));

  return (
    <tr onClick={() => onAction(`进入个股详情：${row.code}`)}>
      <td className="num muted">{rank}</td>
      <td className="stock-cell">
        <strong>{row.name}</strong>
        <br />
        <span className="muted num">{row.code}</span>
      </td>
      <td className={`num ${cls}`}>{formatPoint(row.latestPrice)}</td>
      <td className={`num ${cls}`}>{formatSignedPercent(row.changePct)}</td>
      <td className="num secondary">{row.turnoverRate.toFixed(1)}%</td>
      <td className="num secondary">{row.volumeRatio.toFixed(1)}</td>
      <td className="num secondary">{row.volume}</td>
      <td className="num secondary">{row.amount}</td>
    </tr>
  );
}
