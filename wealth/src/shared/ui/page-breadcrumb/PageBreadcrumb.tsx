import { Fragment, useEffect, useState } from "react";

import "./page-breadcrumb.css";

export interface PageBreadcrumbItem {
  label: string;
  path?: string;
}

export type PageSessionStatus = "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";

interface PageBreadcrumbProps {
  items: readonly PageBreadcrumbItem[];
  sessionStatus: PageSessionStatus;
  onNavigate: (path: string) => void;
}

const weekdays = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];

function formatDateText(now: Date): string {
  return `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日`;
}

function formatTimeText(now: Date): string {
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function formatSessionStatus(status: PageSessionStatus): string {
  if (status === "TRADING") return "交易中";
  if (status === "BREAK") return "午间休市";
  if (status === "PRE_OPEN") return "待开盘";
  return "已收盘";
}

export function PageBreadcrumb({ items, sessionStatus, onNavigate }: PageBreadcrumbProps) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="breadcrumb-row" aria-label="Breadcrumb">
      <div className="breadcrumb">
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          return (
            <Fragment key={`${item.label}-${index}`}>
              {index > 0 ? <span aria-hidden="true">/</span> : null}
              {!isLast && item.path ? (
                <button type="button" onClick={() => onNavigate(item.path!)}>{item.label}</button>
              ) : (
                <span className={isLast ? "current" : undefined}>{item.label}</span>
              )}
            </Fragment>
          );
        })}
      </div>
      <div className="breadcrumb-meta" aria-label="页面时间状态">
        <span>{formatDateText(now)}</span>
        <span>{weekdays[now.getDay()]}</span>
        <span className="num">{formatTimeText(now)}</span>
        <span className="status-pill">
          <span className="status-dot ready" />
          {formatSessionStatus(sessionStatus)}
        </span>
      </div>
    </div>
  );
}
