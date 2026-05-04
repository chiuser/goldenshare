type MetricProps = {
  label: string;
  value: string;
  hint: string;
};

export function Metric({ label, value, hint }: MetricProps) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{hint}</em>
    </article>
  );
}
