import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

class ResizeObserverMock implements ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock;

HTMLCanvasElement.prototype.getContext = function getContext() {
  return {
    arc: () => {},
    beginPath: () => {},
    clearRect: () => {},
    fill: () => {},
    fillRect: () => {},
    fillText: () => {},
    lineTo: () => {},
    moveTo: () => {},
    restore: () => {},
    save: () => {},
    setLineDash: () => {},
    setTransform: () => {},
    stroke: () => {},
  } as unknown as CanvasRenderingContext2D;
} as unknown as typeof HTMLCanvasElement.prototype.getContext;

beforeEach(() => {
  window.localStorage.setItem("wealth.auth.access-token", "test-access-token");
  window.localStorage.setItem("wealth.auth.refresh-token", "test-refresh-token");
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});
