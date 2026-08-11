import type { ReactNode } from "react";

import type { DetailChartAxisFloatLabelState } from "./detailChartTypes";

interface DetailChartPaneProps {
  ariaLabel: string;
  axisFloatLabel?: DetailChartAxisFloatLabelState | null;
  className?: string;
  header: ReactNode;
  hostRef: (node: HTMLDivElement | null) => void;
  overlay?: ReactNode;
}

export function DetailChartPane({
  ariaLabel,
  axisFloatLabel,
  className = "",
  header,
  hostRef,
  overlay,
}: DetailChartPaneProps) {
  return (
    <div className={["detail-chart-panel", className].filter(Boolean).join(" ")} aria-label={ariaLabel}>
      <div className="detail-chart-panel-header">{header}</div>
      <div className="detail-chart-host" ref={hostRef} />
      {overlay}
      {axisFloatLabel ? <DetailChartAxisFloatLabel label={axisFloatLabel} /> : null}
    </div>
  );
}

function DetailChartAxisFloatLabel({ label }: { label: DetailChartAxisFloatLabelState }) {
  return (
    <span
      aria-label="图表Y轴浮标"
      className="detail-chart-axis-float-label"
      style={{ top: `calc(var(--detail-chart-panel-header-height, 28px) + ${label.top}px)` }}
    >
      {label.value}
    </span>
  );
}
