interface MarketStatusPillProps {
  label: string;
  tone?: "ready" | "delayed";
}

export function MarketStatusPill({ label, tone = "ready" }: MarketStatusPillProps) {
  return (
    <span className="status-pill">
      <i className={`status-dot ${tone}`} />
      {label}
    </span>
  );
}
