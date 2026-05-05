import type { ReactNode } from "react";

type SectionCardProps = {
  children: ReactNode;
  className?: string;
  description?: string;
  side?: ReactNode;
  title: string;
  variant?: "default" | "subtle" | "elevated" | "accent" | "warning";
};

export function SectionCard({ children, className = "", description, side, title, variant = "default" }: SectionCardProps) {
  const classes = ["section-card", `section-card-${variant}`, className].filter(Boolean).join(" ");
  return (
    <section className={classes}>
      <div className="section-card-header">
        <div>
          <h3>{title}</h3>
          {description ? <p>{description}</p> : null}
        </div>
        {side ? <div className="section-card-side">{side}</div> : null}
      </div>
      {children}
    </section>
  );
}
