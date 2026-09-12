import { useEffect, useId, useRef, type InputHTMLAttributes, type ReactNode } from "react";
import "./trading-assistant-form.css";

export function TradingAssistantDialog({ title, subtitle, children, footer, onClose, variant = "dialog", showClose = true }: {
  title: string; subtitle?: string; children: ReactNode; footer: ReactNode; onClose: () => void;
  variant?: "dialog" | "drawer" | "onboarding" | "assets" | "recovery" | "fees"; showClose?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement;
    const node = dialog.current!;
    node.showModal();
    return () => { node.close(); if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, []);
  return <dialog ref={dialog} className={`ta-dialog ta-dialog--${variant}`} aria-labelledby={titleId}
    onCancel={event => { event.preventDefault(); close.current(); }}>
    <div className="ta-dialog-heading">
      <div><h2 id={titleId}>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
      {showClose && <button className="ta-close" type="button" aria-label="关闭" onClick={onClose}>×</button>}
    </div>
    <div className="ta-dialog-content">{children}</div>
    <div className="ta-dialog-footer">{footer}</div>
  </dialog>;
}

export function TradingAssistantField({ label, error, hint, ...input }: InputHTMLAttributes<HTMLInputElement> & {
  label: string; error?: string; hint?: string;
}) {
  const id = useId();
  return <div className="ta-field">
    <label htmlFor={id}>{label}{input.required && <span aria-hidden="true"> *</span>}</label>
    <input {...input} id={id} aria-invalid={error ? true : undefined} aria-describedby={error || hint ? `${id}-message` : undefined} />
    {error ? <p className="ta-field-error" id={`${id}-message`} role="alert">{error}</p>
      : hint ? <p className="ta-field-hint" id={`${id}-message`}>{hint}</p> : null}
  </div>;
}

export function TradingAssistantAction({ children, primary = false, danger = false, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { primary?: boolean; danger?: boolean }) {
  return <button {...props} type={props.type ?? "button"} className={`ta-action${danger ? " ta-action--danger" : primary ? " ta-action--primary" : ""}`}>{children}</button>;
}
