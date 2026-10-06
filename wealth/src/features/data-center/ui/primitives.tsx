import { type ButtonHTMLAttributes, type ReactNode } from "react";
import { numberText } from "../model/presentation";
export function Button({ tone, className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "primary" | "danger" }) {
  return <button type="button" className={`dc-button ${tone ?? "secondary"} ${className}`} {...props} />;
}
export function Panel({ title, description, action, children }: { title: string; description?: ReactNode; action?: ReactNode; children?: ReactNode }) {
  return <section className="dc-panel"><div className="dc-panel-head"><div><h2>{title}</h2>{description && <p className="dc-secondary">{description}</p>}</div>{action}</div>{children}</section>;
}
export function Notice({ children, danger = true }: { children: ReactNode; danger?: boolean }) { return <div className={`dc-notice ${danger ? "danger" : "info"}`} role={danger ? "alert" : "status"}>{children}</div>; }
export function Empty({ title, children }: { title: string; children?: ReactNode }) { return <div className="dc-empty"><strong>{title}</strong>{children && <p>{children}</p>}</div>; }
export function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="dc-field"><span>{label}</span><span className="dc-field-control">{children}</span></label>; }
export function Metrics({ items }: { items: readonly [string, number | null, string?][] }) {
  return <div className="dc-metrics">{items.map(([label, value, tone]) => <div key={label}><strong className={`num ${tone ?? ""}`}>{numberText(value)}</strong><span>{label}</span></div>)}</div>;
}
export function Pagination({ previous, next, onPrevious, onNext, children, disabled = false }: { previous: boolean; next: boolean; onPrevious: () => void; onNext: () => void; children?: ReactNode; disabled?: boolean }) {
  return <div className="dc-actions dc-pagination"><span className="dc-secondary">{children}</span><Button disabled={!previous || disabled} onClick={onPrevious}>上一页</Button><Button disabled={!next || disabled} onClick={onNext}>下一页</Button></div>;
}
