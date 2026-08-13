import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { NineTurnLayerViewModel, NineTurnLayerPhase } from "../model/nineTurnTypes";
import { NineTurnLayerStatus } from "./NineTurnLayerStatus";

describe("NineTurnLayerStatus", () => {
  it.each([
    ["LOADING", "正在加载九转序列。"],
    ["EMPTY", "当前窗口暂无九转标记。"],
    ["SOURCE_EMPTY", "九转数据尚未覆盖当前窗口。"],
    ["PARTIAL", "九转数据部分缺失，已展示可确认标记。"],
    ["FORBIDDEN", "当前账号无权查看九转序列。"],
    ["UNSUPPORTED", "当前周期不提供九转序列。"],
    ["ERROR", "九转序列加载失败。"],
  ] as const)("renders the local %s state", (phase, message) => {
    render(<NineTurnLayerStatus droppedMarkerCount={0} layer={layer(phase)} onRetry={vi.fn()} />);

    expect(screen.getByRole("status")).toHaveTextContent(message);
  });

  it("shows an alignment warning and retries only the nine-turn layer", () => {
    const onRetry = vi.fn();
    render(
      <NineTurnLayerStatus
        droppedMarkerCount={2}
        layer={{ ...layer("ERROR"), canRetry: true }}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("2 个九转标记未找到对应 K 线，已隐藏。");
    fireEvent.click(screen.getByRole("button", { name: "重试九转" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

function layer(phase: NineTurnLayerPhase): NineTurnLayerViewModel {
  return {
    canRetry: false,
    data: null,
    errorCode: null,
    markers: [],
    message: null,
    period: "day",
    phase,
  };
}
