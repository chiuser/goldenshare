import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  help?: string;
  meta?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Panel({ title, help, meta, className, children }: PanelProps) {
  return (
    <section className={["panel", className].filter(Boolean).join(" ")} aria-label={title}>
      <div className="section-header">
        <div className="section-title">
          {title}
          {help ? (
            <span className="help" data-tip={help} title={help}>
              ?
            </span>
          ) : null}
        </div>
        {meta}
      </div>
      {children}
    </section>
  );
}
