import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appTheme } from "../../app/theme";
import { StatusBadge } from "./status-badge";

describe("StatusBadge", () => {
  it("uses semantic tones for common operational states", () => {
    render(
      <MantineProvider theme={appTheme}>
        <>
          <StatusBadge value="ok" label="服务正常" />
          <StatusBadge value="healthy" label="健康" />
          <StatusBadge value="running" />
          <StatusBadge value="fresh" />
          <StatusBadge value="paused" />
          <StatusBadge value="failed" />
          <StatusBadge value="disabled" />
        </>
      </MantineProvider>,
    );

    expect(findBadge("服务正常")).toHaveAttribute("data-tone", "success");
    expect(findBadge("健康")).toHaveAttribute("data-tone", "success");
    expect(findBadge("执行中")).toHaveAttribute("data-tone", "info");
    expect(findBadge("正常")).toHaveAttribute("data-tone", "success");
    expect(findBadge("已暂停")).toHaveAttribute("data-tone", "warning");
    expect(findBadge("执行失败")).toHaveAttribute("data-tone", "error");
    expect(findBadge("已停用")).toHaveAttribute("data-tone", "neutral");
  });

  it("falls back to neutral tone and supports custom labels", () => {
    render(
      <MantineProvider theme={appTheme}>
        <>
          <StatusBadge value="mystery" />
          <StatusBadge value="running" label="处理中" />
        </>
      </MantineProvider>,
    );

    expect(findBadge("未定义")).toHaveAttribute("data-tone", "neutral");
    expect(findBadge("处理中")).toHaveAttribute("data-tone", "info");
  });
});

function findBadge(text: string) {
  const badge = screen.getByText(text).closest("[data-tone]");
  expect(badge).not.toBeNull();
  return badge as HTMLElement;
}
