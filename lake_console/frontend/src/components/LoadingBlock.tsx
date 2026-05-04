type LoadingBlockProps = {
  description: string;
  title: string;
};

export function LoadingBlock({ description, title }: LoadingBlockProps) {
  return (
    <div className="loading-block" aria-live="polite">
      <span aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
    </div>
  );
}
