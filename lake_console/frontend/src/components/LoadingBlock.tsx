type LoadingBlockProps = {
  description: string;
  title: string;
  tone?: "processing" | "neutral";
};

export function LoadingBlock({ description, title, tone = "processing" }: LoadingBlockProps) {
  return (
    <div className={`loading-block loading-block-${tone}`} aria-live="polite">
      <span aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
    </div>
  );
}
