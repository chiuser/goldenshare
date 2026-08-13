import type { KeyboardEvent } from "react";
import type { SectorOverviewView } from "./api/marketSectorOverviewApi";

const VIEWS: Array<{ key: SectorOverviewView; label: string }> = [
  { key: "INDUSTRY", label: "行业" },
  { key: "CONCEPT", label: "概念" },
  { key: "REGION", label: "地域" },
];

export function SectorOverviewTabs({
  view,
  onViewChange,
}: {
  view: SectorOverviewView;
  onViewChange: (view: SectorOverviewView) => void;
}) {
  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) {
    const nextIndex = event.key === "ArrowRight"
      ? (currentIndex + 1) % VIEWS.length
      : event.key === "ArrowLeft"
        ? (currentIndex - 1 + VIEWS.length) % VIEWS.length
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? VIEWS.length - 1
            : null;
    if (nextIndex == null) return;
    event.preventDefault();
    onViewChange(VIEWS[nextIndex].key);
    event.currentTarget.parentElement
      ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
      [nextIndex]?.focus();
  }

  return (
    <div aria-label="板块分类" className="sector-tabs" role="tablist">
      {VIEWS.map((item, index) => (
        <button
          aria-selected={view === item.key}
          className={view === item.key ? "active" : ""}
          key={item.key}
          role="tab"
          tabIndex={view === item.key ? 0 : -1}
          type="button"
          onClick={() => onViewChange(item.key)}
          onKeyDown={(event) => handleKeyDown(event, index)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
