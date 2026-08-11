import type { IndexBasicMetric } from "../model/indexDetailTypes";

export function IndexBasicTab({ metrics }: { metrics: IndexBasicMetric[] }) {
  return (
    <section className="index-basic-module" aria-label="基本行情">
      <div className="index-tab-section-title"><strong>基本行情</strong><span>日线口径</span></div>
      <div className="index-basic-grid">
        {metrics.map((metric) => (
          <div className="index-basic-card" data-metric-key={metric.key} key={metric.key}>
            <span>{metric.label}</span><b className={metric.tone}>{metric.value}</b>
          </div>
        ))}
        <div aria-hidden="true" className="index-basic-card-placeholder" />
      </div>
    </section>
  );
}
