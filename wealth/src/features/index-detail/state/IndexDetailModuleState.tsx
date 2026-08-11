interface IndexDetailModuleStateProps {
  actionLabel?: string;
  onAction?: () => void;
  text: string;
  tone?: "muted" | "warning" | "info" | "error";
}

export function IndexDetailModuleState({ actionLabel, onAction, text, tone = "muted" }: IndexDetailModuleStateProps) {
  return (
    <div className={`index-module-state ${tone}`}>
      <span>{text}</span>
      {actionLabel && onAction ? <button type="button" onClick={onAction}>{actionLabel}</button> : null}
    </div>
  );
}
