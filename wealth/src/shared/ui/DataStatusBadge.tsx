interface DataStatusBadgeProps {
  tone?: "ready" | "delayed";
  label: string;
  title?: string;
}

export function DataStatusBadge({ tone = "ready", label, title }: DataStatusBadgeProps) {
  return (
    <span className={`data-badge ${tone}`} title={title}>
      <i className={`status-dot ${tone}`} />
      {label}
    </span>
  );
}
