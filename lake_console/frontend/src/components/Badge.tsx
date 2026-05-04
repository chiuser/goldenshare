import type { ReactNode } from "react";

type BadgeTone = "success" | "warning" | "error" | "muted" | "brand";

type BadgeProps = {
  children: ReactNode;
  className?: string;
  tone?: BadgeTone;
};

export function Badge({ children, className = "", tone = "muted" }: BadgeProps) {
  const classes = ["badge", tone, className].filter(Boolean).join(" ");
  return <span className={classes}>{children}</span>;
}
