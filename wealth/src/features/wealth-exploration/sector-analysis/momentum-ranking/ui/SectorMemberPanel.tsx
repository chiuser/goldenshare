import { useEffect, useRef, useState } from "react";

import type {
  MemberViewState,
  SectorMomentumPeriod,
} from "../model/sectorMomentumTypes";

interface SectorMemberPanelProps {
  memberState: MemberViewState;
  onRetry: () => void;
  period: SectorMomentumPeriod;
  sectorName: string;
}

export function SectorMemberPanel({
  memberState,
  onRetry,
  period,
  sectorName,
}: SectorMemberPanelProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const requestKey = "key" in memberState ? memberState.key : "idle";
  useEffect(() => {
    if (viewportRef.current) viewportRef.current.scrollTop = 0;
  }, [requestKey]);

  const data = memberState.kind === "ready" ? memberState.data : null;
  return (
    <section className="sector-member-panel" aria-label={`${sectorName}成分股`}>
      <div className="sector-member-header">
        <div>
          <OverflowText className="sector-member-title" text={`${sectorName}成分股`} />
          <span className="momentum-period-chip">{period}日</span>
        </div>
        <span className="sector-member-counts">
          {data
            ? `${data.totalMemberCount} 只 · 收盘 ${data.closeAvailableCount} · 可算 ${data.calculableCount}`
            : "-- 只"}
        </span>
      </div>
      <div className="sector-member-table" role="table" aria-label="三级行业成分股明细">
        <div className="sector-member-grid sector-member-table-header" role="row">
          <span role="columnheader">名称</span>
          <span role="columnheader">代码</span>
          <span role="columnheader">收盘价</span>
          <span role="columnheader">区间涨跌幅</span>
        </div>
        <div className="sector-member-viewport" ref={viewportRef}>
          {memberState.kind === "ready" ? memberState.data.rows.map((row) => (
            <div className="sector-member-grid sector-member-row" role="row" key={row.stockCode}>
              <OverflowText className="sector-member-name" role="cell" text={row.stockNameText} />
              <span className="num sector-member-code" role="cell">{row.stockCode}</span>
              <span className="num sector-member-close" role="cell">{row.closeText}</span>
              <span className={`num sector-member-return ${row.directionClass}`} role="cell">{row.returnText}</span>
            </div>
          )) : null}
          {memberState.kind === "idle" || memberState.kind === "loading" ? (
            <div className="sector-member-loading" role="status" aria-label="正在加载成分股">
              {Array.from({ length: 6 }, (_, index) => <i key={index} />)}
            </div>
          ) : null}
          {memberState.kind === "empty" ? (
            <div className="sector-member-local-state" role="status">暂无成分股数据</div>
          ) : null}
          {memberState.kind === "error" ? (
            <div className="sector-member-local-state sector-member-error" role="alert">
              <span>{memberState.message}</span>
              {memberState.retryable ? <button type="button" onClick={onRetry}>重试</button> : null}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function OverflowText({
  className,
  role,
  text,
}: {
  className: string;
  role?: "cell";
  text: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [overflowed, setOverflowed] = useState(false);
  useEffect(() => {
    const measure = () => {
      const node = ref.current;
      setOverflowed(Boolean(node && node.scrollWidth > node.clientWidth));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [text]);
  return <span className={className} ref={ref} role={role} title={overflowed ? text : undefined}>{text}</span>;
}
