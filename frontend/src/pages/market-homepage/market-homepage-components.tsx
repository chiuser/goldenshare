import type { ReactNode } from "react";

import type { HistoryPoint, LadderStage, NavKey, RankItem, Trend } from "./market-homepage-data";

export function TrendText({ children, trend }: { children: ReactNode; trend: Trend }) {
  return <span className={trendClass(trend)}>{children}</span>;
}

export function trendClass(trend: Trend) {
  if (trend === "up") return "up";
  if (trend === "down") return "down";
  if (trend === "flat") return "flat";
  return "neutral";
}

export function Panel({
  title,
  subtitle,
  meta,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  meta?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`.trim()}>
      {title ? (
        <div className="panel-header">
          <div>
            <h2 className="panel-title">{title}</h2>
            {subtitle ? <p className="panel-subtitle">{subtitle}</p> : null}
          </div>
          {meta ? <div className="meta">{meta}</div> : null}
        </div>
      ) : null}
      <div className="body">{children}</div>
    </section>
  );
}

export function TopNav({
  activePage,
  onNavigate,
}: {
  activePage: NavKey;
  onNavigate: (page: NavKey) => void;
}) {
  const navItems: Array<{ key: NavKey; label: string }> = [
    { key: "home", label: "首页" },
    { key: "temperature", label: "市场温度" },
    { key: "emotion", label: "情绪分析" },
    { key: "capital", label: "资金面" },
    { key: "rotation", label: "板块轮动" },
    { key: "watchlist", label: "自选" },
  ];

  return (
    <header className="topbar">
      <div className="brand">
        <div className="logo">财</div>
        <div>
          <h1>财势乾坤</h1>
          <p>行情系统原型 V10 重建版 · 首页 + 情绪分析页</p>
        </div>
      </div>
      <nav className="nav" aria-label="行情系统导航">
        {navItems.map((item) => (
          <button
            className={activePage === item.key ? "active" : ""}
            key={item.key}
            onClick={() => onNavigate(item.key)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div className="tools">
        <div className="search">⌕ 搜索指数 / 板块 / 个股 / 主题</div>
        <div className="chip">
          <span className="dot" />
          交易中 · 14:36
        </div>
      </div>
    </header>
  );
}

export function RankList({ items }: { items: RankItem[] }) {
  return (
    <div className="rank-list">
      {items.map((item, index) => (
        <div className="rank-item" key={item.name}>
          <div className="rank-no">{index + 1}</div>
          <div>
            <h5>{item.name}</h5>
            <p>{item.desc}</p>
          </div>
          <div className="heat">{item.heat}</div>
          <div className={`change ${trendClass(item.trend)}`}>{item.change}</div>
        </div>
      ))}
    </div>
  );
}

export function Tabs({
  items,
  active,
  onChange,
}: {
  items: string[];
  active: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {items.map((item) => (
        <button
          aria-selected={active === item}
          className={`tab ${active === item ? "active" : ""}`}
          key={item}
          onClick={() => onChange(item)}
          role="tab"
          type="button"
        >
          {item}
        </button>
      ))}
    </div>
  );
}

function toLinePoints(values: number[], width: number, height: number, paddingX = 42, paddingY = 26) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const drawableWidth = width - paddingX * 2;
  const drawableHeight = height - paddingY * 2;
  const range = max - min || 1;

  return values.map((value, index) => {
    const x = paddingX + (drawableWidth / Math.max(values.length - 1, 1)) * index;
    const y = paddingY + drawableHeight - ((value - min) / range) * drawableHeight;
    return { x, y, value };
  });
}

export function HistoryLineChart({
  points,
  mode,
  selectedIndex,
  onHoverIndex,
}: {
  points: HistoryPoint[];
  mode: "turnover" | "breadth";
  selectedIndex: number;
  onHoverIndex: (index: number) => void;
}) {
  const width = 460;
  const height = 220;
  const turnoverLine = toLinePoints(points.map((point) => point.turnover), width, height);
  const risingLine = toLinePoints(points.map((point) => point.rising), width, height);
  const fallingLine = toLinePoints(points.map((point) => point.falling), width, height);
  const activePoint = mode === "turnover" ? turnoverLine[selectedIndex] : risingLine[selectedIndex];

  const labels = points.map((point, index) => (
    <text fill="#6f8098" fontSize="10" key={point.date} x={38 + index * (392 / Math.max(points.length - 1, 1))} y="206">
      {point.date}
    </text>
  ));

  return (
    <div className="svg-wrap">
      <svg
        aria-label={mode === "turnover" ? "历史成交额图" : "历史涨跌图"}
        height="100%"
        onMouseLeave={() => onHoverIndex(points.length - 1)}
        preserveAspectRatio="none"
        viewBox="0 0 460 220"
        width="100%"
      >
        <g stroke="rgba(143,161,184,.16)">
          <line x1="42" x2="42" y1="24" y2="190" />
          <line x1="42" x2="434" y1="190" y2="190" />
          {[58, 92, 126, 160].map((y) => (
            <line key={y} strokeDasharray="4 4" x1="42" x2="434" y1={y} y2={y} />
          ))}
        </g>
        {mode === "turnover" ? (
          <>
            <polygon
              fill="rgba(247,199,107,.12)"
              points={`${turnoverLine.map((point) => `${point.x},${point.y}`).join(" ")} ${turnoverLine.at(-1)?.x ?? 42},190 42,190`}
            />
            <polyline fill="none" points={turnoverLine.map((point) => `${point.x},${point.y}`).join(" ")} stroke="#f7c76b" strokeWidth="3" />
            {turnoverLine.map((point, index) => (
              <circle
                cx={point.x}
                cy={point.y}
                fill="#f7c76b"
                key={points[index].date}
                onMouseEnter={() => onHoverIndex(index)}
                r={index === selectedIndex ? 6 : 4}
              />
            ))}
          </>
        ) : (
          <>
            <polyline fill="none" points={risingLine.map((point) => `${point.x},${point.y}`).join(" ")} stroke="#ff4d5a" strokeWidth="3" />
            <polyline fill="none" points={fallingLine.map((point) => `${point.x},${point.y}`).join(" ")} stroke="#15c784" strokeWidth="3" />
            {risingLine.map((point, index) => (
              <circle cx={point.x} cy={point.y} fill="#ff4d5a" key={`rise-${points[index].date}`} onMouseEnter={() => onHoverIndex(index)} r={index === selectedIndex ? 6 : 4} />
            ))}
            {fallingLine.map((point, index) => (
              <circle cx={point.x} cy={point.y} fill="#15c784" key={`fall-${points[index].date}`} onMouseEnter={() => onHoverIndex(index)} r={index === selectedIndex ? 6 : 4} />
            ))}
          </>
        )}
        {activePoint ? (
          <g className="chart-tooltip">
            <line stroke="rgba(255,255,255,.28)" strokeDasharray="4 4" x1={activePoint.x} x2={activePoint.x} y1="24" y2="190" />
            <rect fill="rgba(5,10,18,.92)" height="44" rx="10" stroke="rgba(255,255,255,.12)" width="116" x={Math.min(activePoint.x + 10, 330)} y={Math.max(activePoint.y - 58, 24)} />
            <text fill="#e5edf8" fontSize="11" x={Math.min(activePoint.x + 22, 342)} y={Math.max(activePoint.y - 34, 48)}>
              {points[selectedIndex].date}
            </text>
            <text fill="#8fa1b8" fontSize="10" x={Math.min(activePoint.x + 22, 342)} y={Math.max(activePoint.y - 16, 66)}>
              {mode === "turnover" ? `${points[selectedIndex].turnover.toLocaleString("zh-CN")} 亿` : `涨 ${points[selectedIndex].rising} / 跌 ${points[selectedIndex].falling}`}
            </text>
          </g>
        ) : null}
        <g>{labels}</g>
        {points.map((point, index) => (
          <rect
            data-testid={`${mode}-hover-${point.date}`}
            fill="transparent"
            height="220"
            key={`${mode}-${point.date}`}
            onMouseEnter={() => onHoverIndex(index)}
            width={460 / points.length}
            x={(460 / points.length) * index}
            y="0"
          />
        ))}
      </svg>
    </div>
  );
}

export function RangeTabs({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  return (
    <div className="tabs range-tabs" role="tablist" aria-label="日期范围">
      {[5, 10, 20].map((item) => (
        <button
          aria-selected={value === item}
          className={`tab ${value === item ? "active" : ""}`}
          key={item}
          onClick={() => onChange(item)}
          role="tab"
          type="button"
        >
          {item}日
        </button>
      ))}
    </div>
  );
}

export function LadderStageColumn({
  stage,
  onOpen,
}: {
  stage: LadderStage;
  onOpen: (stage: LadderStage) => void;
}) {
  return (
    <div className={`stage-col ${stage.levelClass}`}>
      <div className="stage-top">
        <span className="stage-level">{stage.label}</span>
        <button className="stage-count" onClick={() => onOpen(stage)} type="button">
          {stage.count}
        </button>
      </div>
      <div className="stage-list">
        {stage.stocks.slice(0, 3).map((stock) => (
          <div className="stock-chip" key={stock.name}>
            <h5>{stock.name}</h5>
            <p>{stock.desc}</p>
            <strong className="up">{stock.meta}</strong>
          </div>
        ))}
      </div>
      <button className="stage-more" onClick={() => onOpen(stage)} type="button">
        查看全部 {stage.count} 只
      </button>
    </div>
  );
}

export function StockDrawer({
  stage,
  onClose,
}: {
  stage: LadderStage | null;
  onClose: () => void;
}) {
  return (
    <div className={`drawer-overlay ${stage ? "show" : ""}`} onClick={(event) => event.target === event.currentTarget && onClose()}>
      <aside aria-label="连板股票列表" aria-modal="true" className="drawer-panel" role="dialog">
        <div className="drawer-header">
          <div>
            <h3>{stage ? `${stage.label} · 全部 ${stage.count} 只` : "连板股票列表"}</h3>
            <p>默认按连板梯队展示完整股票列表，可继续扩展行业筛选、排序和搜索。</p>
          </div>
          <button aria-label="关闭抽屉" className="drawer-close" onClick={onClose} type="button">
            ×
          </button>
        </div>
        <div className="drawer-body">
          <div className="drawer-title">股票列表</div>
          {stage?.stocks.map((stock) => (
            <div className="drawer-item" key={stock.name}>
              <div>
                <h5>{stock.name}</h5>
                <p>{stock.desc}</p>
              </div>
              <div className="drawer-meta">
                <strong>{stage.label}</strong>
                <span>{stock.meta}</span>
              </div>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
