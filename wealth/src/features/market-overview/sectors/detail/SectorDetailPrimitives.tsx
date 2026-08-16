import type { CSSProperties } from "react";
import { formatSignedPercent } from "../../../../shared/lib/formatters";
import { directionClass, directionFromNumber } from "../../../../shared/lib/marketDirection";
import type {
  ConceptHeatPoint,
  HeatLevel,
  HeatTrend,
  SectorLeaderStock,
  SectorMemberStock,
} from "../api/marketSectorOverviewApi";

export function MetricGrid({ items }: { items: Array<{ label: string; value: string; className?: string }> }) {
  return (
    <div className="sector-detail-metrics">
      {items.map((item) => (
        <div key={item.label}>
          <span>{item.label}</span>
          <strong className={item.className}>{item.value}</strong>
        </div>
      ))}
    </div>
  );
}

export function SectorLeaderCard({
  leader,
  onStockSelect,
}: {
  leader: SectorLeaderStock | null;
  onStockSelect: (stockCode: string) => void;
}) {
  if (!leader?.stockCode) {
    return (
      <div className="sector-leader-card is-empty">
        <span>领涨股</span>
        <strong>暂无领涨股</strong>
      </div>
    );
  }
  const name = leader.stockName || leader.stockCode;
  return (
    <div className="sector-leader-card">
      <span>领涨股</span>
      <button
        aria-label={`进入${name}股票详情`}
        title={name}
        type="button"
        onClick={() => onStockSelect(leader.stockCode as string)}
      >
        <strong>{name}</strong>
        <small>{leader.stockCode}</small>
      </button>
      <em className={directionClass(directionFromNumber(leader.changePct))}>{leader.changePct == null ? "--" : formatSignedPercent(leader.changePct)}</em>
    </div>
  );
}

export function SectorMemberStockList({
  members,
  title,
  onStockSelect,
}: {
  members: SectorMemberStock[];
  title: string;
  onStockSelect: (stockCode: string) => void;
}) {
  return (
    <div className="sector-members">
      <header><strong>{title}</strong><span>{members.length}只 · 按涨跌幅</span></header>
      <div className="sector-members-head"><span>股票</span><span>涨跌幅</span></div>
      {members.map((member) => {
        const name = member.stockName || member.stockCode;
        return (
          <button
            aria-label={`进入${name}股票详情`}
            key={member.stockCode}
            type="button"
            onClick={() => onStockSelect(member.stockCode)}
          >
            <span title={name}>{name} <small>{member.stockCode}</small></span>
            <span className={directionClass(member.direction)}>{member.changePct == null ? "--" : formatSignedPercent(member.changePct)}</span>
          </button>
        );
      })}
      {!members.length ? <div className="sector-list-empty">暂无有效成分行情</div> : null}
    </div>
  );
}

export function SectorRankLeader({
  leader,
  onStockSelect,
}: {
  leader: SectorLeaderStock | null;
  onStockSelect: (stockCode: string) => void;
}) {
  if (!leader?.stockCode) return <span className="sector-rank-no-leader">暂无领涨股</span>;
  const name = leader.stockName || leader.stockCode;
  return (
    <button
      aria-label={`进入${name}股票详情`}
      className="sector-rank-leader"
      title={name}
      type="button"
      onClick={() => onStockSelect(leader.stockCode as string)}
    >
      <span>{name}</span>
      <strong className={directionClass(directionFromNumber(leader.changePct))}>{leader.changePct == null ? "--" : formatSignedPercent(leader.changePct)}</strong>
    </button>
  );
}

export function HeatLevelBadge({ level }: { level: HeatLevel }) {
  if (level === "NONE") return null;
  const label: Record<Exclude<HeatLevel, "NONE">, string> = {
    BOILING: "沸腾",
    HOT: "高热",
    ACTIVE: "活跃",
  };
  return <span className={`heat-level-badge ${level.toLowerCase()}`}>{label[level]}</span>;
}

export function HeatTrendBadge({ trend }: { trend: HeatTrend }) {
  if (trend === "UNKNOWN") return null;
  const label: Record<Exclude<HeatTrend, "UNKNOWN">, string> = {
    HEATING: "升温",
    STABLE: "平稳",
    COOLING: "降温",
  };
  return <span className={`heat-trend-badge ${trend.toLowerCase()}`}>{label[trend]}</span>;
}

export function ConceptHeatHistory({ points }: { points: ConceptHeatPoint[] }) {
  const visiblePoints = points.slice(0, 20);
  const dateTickIndexes = new Set([0, 4, 9, 14, 19]);

  return (
    <section className="concept-heat-history">
      <header><strong>近 20 个交易日热度</strong></header>
      <div aria-label="近20个交易日热度" className="concept-heat-bars">
        {visiblePoints.map((point) => {
          const heatScore = point.heatScore;
          const isGap = heatScore == null;
          const displayScore = heatScore == null ? null : Number(heatScore.toFixed(2)).toString();
          const style = heatScore == null
            ? undefined
            : ({ "--heat-height": `${Math.max(0, Math.min(100, heatScore)) * 0.42}px` } as CSSProperties);
          return (
            <span
              aria-label={`${point.tradeDate} ${isGap ? "无有效热度" : point.heatScore}`}
              className={`concept-heat-slot${isGap ? " is-gap" : ""}`}
              key={point.tradeDate}
              role="img"
              title={`${point.tradeDate} · ${isGap ? "无有效热度" : point.heatScore}`}
            >
              {isGap ? null : (
                <>
                  <span aria-hidden="true" className="concept-heat-value" style={style}>{displayScore}</span>
                  <span aria-hidden="true" className={`concept-heat-bar ${point.heatLevel.toLowerCase()}`} style={style} />
                </>
              )}
            </span>
          );
        })}
      </div>
      <div aria-hidden="true" className="concept-heat-dates">
        {visiblePoints.map((point, index) => (
          <span className="concept-heat-date-slot" key={point.tradeDate}>
            {dateTickIndexes.has(index) ? <time dateTime={point.tradeDate}>{point.tradeDate.slice(5)}</time> : null}
          </span>
        ))}
      </div>
    </section>
  );
}

export function formatAmount(value: number | null): string {
  if (value == null) return "--";
  const scaled = value / 100_000_000;
  return `${scaled > 0 ? "+" : ""}${scaled.toFixed(Math.abs(scaled) >= 100 ? 0 : 1)}亿`;
}

export function formatCount(value: number | null): string {
  return value == null ? "--" : String(value);
}
