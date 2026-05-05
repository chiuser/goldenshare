import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "info" | "success" | "warning" | "error" | "processing" | "muted" | "brand";

type BadgeProps = {
  children: ReactNode;
  className?: string;
  tone?: BadgeTone;
};

export function Badge({ children, className = "", tone = "muted" }: BadgeProps) {
  const classes = ["badge", tone, className].filter(Boolean).join(" ");
  return <span className={classes}>{children}</span>;
}
