import { MantineProvider, Stack, Text } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appTheme } from "../../app/theme";
import { AlertBar, AlertBarNote } from "./alert-bar";

describe("AlertBar", () => {
  it("renders semantic tones and keeps alert semantics", () => {
    render(
      <MantineProvider theme={appTheme}>
        <Stack>
          <AlertBar tone="neutral" title="暂无新进展">系统还在等待下一次写回。</AlertBar>
          <AlertBar tone="info" title="处理中">正在刷新任务状态。</AlertBar>
          <AlertBar tone="success" title="任务已结束">处理结果已经写回。</AlertBar>
          <AlertBar tone="warning" title="需要留意">当前进度写回稍有延迟。</AlertBar>
          <AlertBar tone="error" title="读取失败">请稍后重试。</AlertBar>
        </Stack>
      </MantineProvider>,
    );

    expect(findAlert("暂无新进展")).toHaveAttribute("data-tone", "neutral");
    expect(findAlert("处理中")).toHaveAttribute("data-tone", "info");
    expect(findAlert("任务已结束")).toHaveAttribute("data-tone", "success");
    expect(findAlert("需要留意")).toHaveAttribute("data-tone", "warning");
    expect(findAlert("读取失败")).toHaveAttribute("data-tone", "error");
  });

  it("supports rich content and secondary notes", () => {
    render(
      <MantineProvider theme={appTheme}>
        <AlertBar tone="warning" title="最近更新：步骤二">
          <Text size="sm">系统还在等待下一次写回。</Text>
          <AlertBarNote>更新时间：2026-04-20 09:18</AlertBarNote>
        </AlertBar>
      </MantineProvider>,
    );

    expect(screen.getByText("系统还在等待下一次写回。")).toBeInTheDocument();
    expect(screen.getByText("更新时间：2026-04-20 09:18")).toBeInTheDocument();
  });
});

function findAlert(title: string) {
  const alert = screen.getByText(title).closest("[data-tone]");
  expect(alert).not.toBeNull();
  return alert as HTMLElement;
}
