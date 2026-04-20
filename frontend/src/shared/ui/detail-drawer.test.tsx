import { Button, MantineProvider, Text } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { appTheme } from "../../app/theme";
import { DetailDrawer, DETAIL_DRAWER_WIDTHS } from "./detail-drawer";

describe("DetailDrawer", () => {
  it("renders title, description and footer actions", () => {
    render(
      <MantineProvider theme={appTheme}>
        <DetailDrawer
          description="用于查看或编辑当前任务的详细配置。"
          footer={
            <>
              <Button variant="default">取消</Button>
              <Button>保存修改</Button>
            </>
          }
          onClose={vi.fn()}
          opened
          title="修改自动任务"
          withinPortal={false}
        >
          <Text>抽屉内容</Text>
        </DetailDrawer>
      </MantineProvider>,
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("修改自动任务")).toBeInTheDocument();
    expect(screen.getByText("用于查看或编辑当前任务的详细配置。")).toBeInTheDocument();
    expect(screen.getByText("抽屉内容")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存修改" })).toBeInTheDocument();
  });

  it("maps size presets to fixed drawer widths", () => {
    expect(DETAIL_DRAWER_WIDTHS.sm).toBe(400);
    expect(DETAIL_DRAWER_WIDTHS.md).toBe(600);
    expect(DETAIL_DRAWER_WIDTHS.lg).toBe(800);
  });
});
