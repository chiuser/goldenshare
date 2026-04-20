import { Button, MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appTheme } from "../../app/theme";
import { TableShell } from "./table-shell";

describe("TableShell", () => {
  it("renders toolbar, summary, and table content when data exists", () => {
    render(
      <MantineProvider theme={appTheme}>
        <TableShell
          hasData
          toolbar={<Button variant="light">刷新列表</Button>}
          summary={<div>最近一次任务操作</div>}
        >
          <div role="table">任务表格</div>
        </TableShell>
      </MantineProvider>,
    );

    expect(screen.getByRole("button", { name: "刷新列表" })).toBeInTheDocument();
    expect(screen.getByText("最近一次任务操作")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("renders empty state when data is absent", () => {
    render(
      <MantineProvider theme={appTheme}>
        <TableShell
          hasData={false}
          emptyState={<div>当前没有表格数据</div>}
        >
          <div role="table">任务表格</div>
        </TableShell>
      </MantineProvider>,
    );

    expect(screen.getByText("当前没有表格数据")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders loader while table data is loading", () => {
    render(
      <MantineProvider theme={appTheme}>
        <TableShell hasData={false} loading emptyState={<div>当前没有表格数据</div>}>
          <div role="table">任务表格</div>
        </TableShell>
      </MantineProvider>,
    );

    expect(screen.getByLabelText("表格加载中")).toBeInTheDocument();
    expect(screen.queryByText("当前没有表格数据")).not.toBeInTheDocument();
  });
});
