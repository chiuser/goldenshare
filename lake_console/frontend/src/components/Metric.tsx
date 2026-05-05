type MetricProps = {
  label: string;
  value: string;
  hint: string;
  variant?: "default" | "subtle" | "elevated" | "accent" | "info" | "success" | "warning" | "error";
};

export function Metric({ label, value, hint, variant = "default" }: MetricProps) {
  return (
    <article className={`metric-card metric-card-${variant}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{hint}</em>
    </article>
  );
}
