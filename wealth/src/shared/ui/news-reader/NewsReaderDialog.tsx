import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { SanitizedHtmlContent } from "./SanitizedHtmlContent";
import type { NewsReaderDialogState, NewsReaderMode, NewsReaderViewModel } from "./newsReaderTypes";
import "./news-reader.css";


const NEWS_READER_IFRAME_TIMEOUT_MS = 12_000;


interface NewsReaderDialogProps {
  state: NewsReaderDialogState;
  onClose: () => void;
  onRetry: () => void;
}


export function NewsReaderDialog({ state, onClose, onRetry }: NewsReaderDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const open = state.status !== "closed";

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      window.requestAnimationFrame(() => closeButtonRef.current?.focus({ preventScroll: true }));
    }
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    const previousPaddingRight = document.body.style.paddingRight;
    const scrollbarGap = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = "hidden";
    if (scrollbarGap > 0) document.body.style.paddingRight = `${scrollbarGap}px`;
    return () => {
      document.body.style.overflow = previousOverflow;
      document.body.style.paddingRight = previousPaddingRight;
    };
  }, [open]);

  if (typeof document === "undefined") return null;

  const header = readHeader(state);
  return createPortal(
    <dialog
      aria-describedby="news-reader-state-description"
      aria-labelledby="news-reader-title"
      className="news-reader-dialog"
      ref={dialogRef}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="news-reader-shell">
        <header className="news-reader-header">
          <div className="news-reader-heading">
            <h2 id="news-reader-title">{header.title}</h2>
            <div className="news-reader-meta">
              {header.publishTime ? <time>{header.publishTime}</time> : null}
              {header.source ? <span>来源：{header.source}</span> : null}
            </div>
          </div>
          <button
            aria-label="关闭新闻阅读器"
            autoFocus
            className="news-reader-close"
            ref={closeButtonRef}
            title="关闭"
            type="button"
            onClick={onClose}
          >
            <svg
              aria-hidden="true"
              data-icon-ref="material:close"
              focusable="false"
              viewBox="0 -960 960 960"
            >
              <path d="M256-213.85 213.85-256l224-224-224-224L256-746.15l224 224 224-224L746.15-704l-224 224 224 224L704-213.85l-224-224-224 224Z" />
            </svg>
          </button>
        </header>
        <div className="news-reader-body" id="news-reader-state-description">
          <NewsReaderBody state={state} onRetry={onRetry} />
        </div>
      </div>
    </dialog>,
    document.body,
  );
}


function NewsReaderBody({ state, onRetry }: { state: NewsReaderDialogState; onRetry: () => void }) {
  if (state.status === "closed") return null;
  if (state.status === "loading") return <NewsReaderLoading mode={state.readerMode} />;
  if (state.status === "empty") {
    return <NewsReaderState title="内容暂不可读" message={state.message} />;
  }
  if (state.status === "error") {
    return (
      <NewsReaderState
        title="新闻加载失败"
        message={state.message}
        action={state.retryable ? <button type="button" onClick={onRetry}>重新加载</button> : null}
      />
    );
  }
  return <NewsReaderReady item={state.item} />;
}


function NewsReaderReady({ item }: { item: NewsReaderViewModel }) {
  if (item.readerMode === "URL" && item.url) return <NewsReaderUrlFrame item={item} />;
  if (item.readerMode === "HTML" && item.html) return <SanitizedHtmlContent html={item.html} />;
  if (item.readerMode === "TEXT" && item.content) {
    return <article className="news-reader-text">{item.content}</article>;
  }
  return <NewsReaderState title="内容暂不可读" message="新闻正文合同不完整。" />;
}


function NewsReaderUrlFrame({ item }: { item: NewsReaderViewModel }) {
  const [frameState, setFrameState] = useState<"loading" | "ready" | "error">("loading");
  const [frameKey, setFrameKey] = useState(0);
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    setFrameState("loading");
    timeoutRef.current = window.setTimeout(() => {
      timeoutRef.current = null;
      setFrameState("error");
    }, NEWS_READER_IFRAME_TIMEOUT_MS);
    return () => {
      if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    };
  }, [item.newsId, frameKey]);

  return (
    <div className="news-reader-frame-wrap">
      {frameState === "loading" ? <NewsReaderLoading mode="URL" compact /> : null}
      {frameState === "error" ? (
        <NewsReaderState
          title="页面暂时无法嵌入"
          message="目标页面可能限制站内展示，也可能加载超时。"
          action={<button type="button" onClick={() => setFrameKey((value) => value + 1)}>重新加载</button>}
        />
      ) : null}
      <iframe
        className={frameState === "ready" ? "news-reader-frame ready" : "news-reader-frame"}
        key={frameKey}
        referrerPolicy="no-referrer"
        sandbox="allow-scripts"
        src={item.url ?? undefined}
        title={item.title}
        onLoad={() => {
          if (frameState === "error") return;
          if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
          timeoutRef.current = null;
          setFrameState("ready");
        }}
      />
    </div>
  );
}


function NewsReaderLoading({ mode, compact = false }: { mode: NewsReaderMode; compact?: boolean }) {
  return (
    <div className={compact ? "news-reader-loading compact" : "news-reader-loading"} data-reader-mode={mode}>
      <span className="news-reader-loading-line wide" />
      <span className="news-reader-loading-line" />
      <span className="news-reader-loading-line medium" />
      <span className="news-reader-loading-line wide" />
      <span className="news-reader-loading-line short" />
    </div>
  );
}


function NewsReaderState({
  title,
  message,
  action,
}: {
  title: string;
  message: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="news-reader-state">
      <strong>{title}</strong>
      <span>{message}</span>
      {action}
    </div>
  );
}


function readHeader(state: NewsReaderDialogState): { title: string; source: string | null; publishTime: string } {
  if (state.status === "closed") return { title: "新闻阅读器", source: null, publishTime: "" };
  if (state.status === "ready") {
    return {
      title: state.item.title,
      source: state.item.source,
      publishTime: state.item.displayPublishTime,
    };
  }
  return { title: state.title, source: null, publishTime: formatPublishTime(state.publishTime) };
}


function formatPublishTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
    hour12: false,
  }).format(parsed);
}
