import type { ReactNode } from "react";

type PageHeaderProps = {
  eyebrow?: string;
  title: string;
  description?: string;
  helpTitle?: string;
  right?: ReactNode;
};

export function PageHeader({ eyebrow, title, description, helpTitle, right }: PageHeaderProps) {
  return (
    <div className="page-header">
      <div>
        {eyebrow ? <span className="page-eyebrow">{eyebrow}</span> : null}
        <h2>
          {title}
          {helpTitle ? (
            <span className="help-mark" title={helpTitle} aria-label="页面说明">
              ?
            </span>
          ) : null}
        </h2>
        {description ? <p>{description}</p> : null}
      </div>
      {right ? <div className="page-header-side">{right}</div> : null}
    </div>
  );
}
