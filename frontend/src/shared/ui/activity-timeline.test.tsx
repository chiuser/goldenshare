import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appTheme } from "../../app/theme";
import { ActivityTimeline } from "./activity-timeline";

describe("ActivityTimeline", () => {
  it("renders timeline items with time and meta", () => {
    render(
      <MantineProvider theme={appTheme}>
        <ActivityTimeline
          items={[
            {
              id: 1,
              title: "步骤一",
              time: "开始：2026-04-20 09:00",
              meta: <span>执行中</span>,
              body: <span>系统正在处理。</span>,
            },
          ]}
        />
      </MantineProvider>,
    );

    expect(screen.getByText("步骤一")).toBeInTheDocument();
    expect(screen.getByText("开始：2026-04-20 09:00")).toBeInTheDocument();
    expect(screen.getByText("执行中")).toBeInTheDocument();
    expect(screen.getByText("系统正在处理。")).toBeInTheDocument();
  });

  it("renders empty state when no items exist", () => {
    render(
      <MantineProvider theme={appTheme}>
        <ActivityTimeline items={[]} emptyState={<div>暂无时间线数据</div>} />
      </MantineProvider>,
    );

    expect(screen.getByText("暂无时间线数据")).toBeInTheDocument();
  });
});
