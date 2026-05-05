import type { ReactNode } from "react";

type DenseToolbarProps = {
  children: ReactNode;
  className?: string;
};

export function DenseToolbar({ children, className = "" }: DenseToolbarProps) {
  const classes = ["dense-toolbar", className].filter(Boolean).join(" ");
  return <div className={classes}>{children}</div>;
}
