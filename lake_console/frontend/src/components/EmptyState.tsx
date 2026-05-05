type EmptyStateProps = {
  title: string;
  description: string;
  tone?: "neutral" | "info" | "warning";
};

export function EmptyState({ title, description, tone = "neutral" }: EmptyStateProps) {
  return (
    <div className={`empty-state empty-state-${tone}`}>
      <span aria-hidden="true" />
      <strong>{title}</strong>
      <p>{description}</p>
    </div>
  );
}
