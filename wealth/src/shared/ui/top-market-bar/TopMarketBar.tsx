import { formatPoint, formatSignedPercent } from "../../lib/formatters";
import { directionClass } from "../../lib/marketDirection";
import "./top-market-bar.css";
import type { TopMarketNavKey, TopMarketTicker } from "./topMarketBarTypes";

const logoUrl = new URL("../../../../docs/reference/brand/logo/logo_new.png", import.meta.url).href;

interface TopMarketBarProps {
  activeNav: TopMarketNavKey;
  tickers: readonly TopMarketTicker[];
  onNavigate: (target: TopMarketNavKey) => void;
  onTickerSelect: (tsCode: string) => void;
}

const navItems: readonly { key: TopMarketNavKey; label: string }[] = [
  { key: "market", label: "乾坤行情" },
  { key: "exploration", label: "财势探查" },
  { key: "assistant", label: "交易助手" },
  { key: "training", label: "交易训练" },
  { key: "data", label: "数据中心" },
  { key: "settings", label: "系统设置" },
];

export function TopMarketBar({ activeNav, tickers, onNavigate, onTickerSelect }: TopMarketBarProps) {

  return (
    <header className="top-market-bar" aria-label="TopMarketBar">
      <button className="brand" type="button" onClick={() => onNavigate("market")}>
        <img alt="财势乾坤" className="brand-logo" src={logoUrl} />
        <span className="brand-copy">
          <span className="brand-title">财势乾坤</span>
          <span className="brand-subtitle">专业投研平台</span>
        </span>
      </button>
      <nav className="system-nav" aria-label="一级系统入口">
        {navItems.map((item) => (
          <button
            className={item.key === activeNav ? "active" : ""}
            key={item.key}
            type="button"
            onClick={() => onNavigate(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div className="ticker-strip" aria-label="主要指数行情条">
        <div className="ticker-track">
          <div className="ticker-segment">
            {tickers.map((ticker) => (
              <button
                className="ticker-item"
                key={`${ticker.code}-main`}
                type="button"
                onClick={() => onTickerSelect(ticker.code)}
              >
                <span className="ticker-name">{ticker.name}</span>
                <span className={`num ${directionClass(ticker.direction)}`}>{formatPoint(ticker.point)}</span>
                <span className={`ticker-meta num ${directionClass(ticker.direction)}`}>{formatSignedPercent(ticker.pct)}</span>
              </button>
            ))}
          </div>
          <div aria-hidden="true" className="ticker-segment ticker-segment-clone">
            {tickers.map((ticker) => (
              <div className="ticker-item ticker-item-clone" key={`${ticker.code}-clone`}>
                <span className="ticker-name">{ticker.name}</span>
                <span className={`num ${directionClass(ticker.direction)}`}>{formatPoint(ticker.point)}</span>
                <span className={`ticker-meta num ${directionClass(ticker.direction)}`}>{formatSignedPercent(ticker.pct)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="top-meta">
        <div className="user-entry" title="用户入口">
          明
        </div>
      </div>
    </header>
  );
}
