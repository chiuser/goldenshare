type ErrorStateBlockProps = {
  description: string;
  title: string;
};

export function ErrorStateBlock({ description, title }: ErrorStateBlockProps) {
  return (
    <div className="error-state-block" role="alert">
      <span aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
    </div>
  );
}
