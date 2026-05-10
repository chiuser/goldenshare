import { useEffect, useState } from "react";
import type { QuoteItem } from "../api/marketOverviewTypes";
import { directionClass } from "../../../shared/lib/marketDirection";
import { formatPoint, formatSignedPercent } from "../../../shared/lib/formatters";
import { DataStatusBadge } from "../../../shared/ui/DataStatusBadge";
import { MarketStatusPill } from "../../../shared/ui/MarketStatusPill";

const logoUrl = new URL("../../../../docs/reference/brand/logo/logo_new.png", import.meta.url).href;

interface TopMarketBarProps {
  tickers: QuoteItem[];
  statusText: string;
  dataDelayText: string;
  onAction: (message: string) => void;
}

function formatClockTime(now: Date): string {
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export function TopMarketBar({ tickers, statusText, dataDelayText, onAction }: TopMarketBarProps) {
  const navItems = ["乾坤行情", "财势探查", "交易助手", "交易训练", "数据中心", "系统设置"];
  const [clockTime, setClockTime] = useState(() => formatClockTime(new Date()));

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClockTime(formatClockTime(new Date()));
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <header className="top-market-bar" aria-label="TopMarketBar">
      <button className="brand" type="button" onClick={() => onAction("跳转：/market/overview")}>
        <img alt="财势乾坤" className="brand-logo" src={logoUrl} />
        <span className="brand-copy">
          <span className="brand-title">财势乾坤</span>
          <span className="brand-subtitle">专业投研平台</span>
        </span>
      </button>
      <nav className="system-nav" aria-label="一级系统入口">
        {navItems.map((item) => (
          <button
            className={item === "乾坤行情" ? "active" : ""}
            key={item}
            type="button"
            onClick={() => onAction(`跳转：${item}`)}
          >
            {item}
          </button>
        ))}
      </nav>
      <div className="ticker-strip" aria-label="主要指数行情条">
        <div className="ticker-track">
          <div className="ticker-segment">
            {tickers.map((ticker) => (
              <button className="ticker-item" key={`${ticker.code}-main`} type="button" onClick={() => onAction(`进入详情：${ticker.code}`)}>
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
        <span className="num" aria-label="系统时间">
          {clockTime}
        </span>
        <MarketStatusPill label={statusText} />
        <DataStatusBadge label={dataDelayText} tone="delayed" title="部分盘中数据为延迟源，历史数据已就绪" />
        <div className="user-entry" title="用户入口">
          明
        </div>
      </div>
    </header>
  );
}
