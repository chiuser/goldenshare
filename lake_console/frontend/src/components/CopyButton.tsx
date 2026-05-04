import { useEffect, useRef, useState } from "react";

type CopyButtonProps = {
  className?: string;
  copiedLabel?: string;
  idleLabel?: string;
  value: string;
};

export function CopyButton({ className = "", copiedLabel = "已复制", idleLabel = "复制", value }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const timeoutRef = useRef<number | null>(null);
  const classes = ["copy-button", className].filter(Boolean).join(" ");

  useEffect(() => () => {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
    }
  }, []);

  async function copyValue() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
      }
      timeoutRef.current = window.setTimeout(() => {
        setCopied(false);
        timeoutRef.current = null;
      }, 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button className={classes} type="button" onClick={copyValue}>
      {copied ? copiedLabel : idleLabel}
    </button>
  );
}
