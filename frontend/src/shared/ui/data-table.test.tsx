import { Button, MantineProvider } from "@mantine/core";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { appTheme } from "../../app/theme";
import { DataTable, type DataTableColumn } from "./data-table";

interface DemoRow {
  id: number;
  name: string;
  status: string;
}

const columns: DataTableColumn<DemoRow>[] = [
  {
    key: "name",
    header: "任务名称",
    align: "left",
    render: (row) => row.name,
    width: "60%",
  },
  {
    key: "status",
    header: "当前状态",
    render: (row) => row.status,
    width: "40%",
  },
];

describe("DataTable", () => {
  it("renders toolbar, summary, and row content", () => {
    render(
      <MantineProvider theme={appTheme}>
        <DataTable
          columns={columns}
          getRowKey={(row) => row.id}
          rows={[
            { id: 1, name: "同步股票日线", status: "执行成功" },
            { id: 2, name: "同步指数成分", status: "等待处理" },
          ]}
          summary={<div>最近一次任务操作</div>}
          toolbar={<Button variant="light">刷新列表</Button>}
        />
      </MantineProvider>,
    );

    expect(screen.getByRole("button", { name: "刷新列表" })).toBeInTheDocument();
    expect(screen.getByText("最近一次任务操作")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "任务名称" })).toBeInTheDocument();
    expect(screen.getByText("同步股票日线")).toBeInTheDocument();
    expect(screen.getByText("等待处理")).toBeInTheDocument();
  });

  it("supports row props for selectable rows", () => {
    const onSelect = vi.fn();

    render(
      <MantineProvider theme={appTheme}>
        <DataTable
          columns={columns}
          getRowKey={(row) => row.id}
          getRowProps={(row) => ({
            "data-selected": row.id === 2 ? "true" : "false",
            onClick: () => onSelect(row.id),
          })}
          rows={[
            { id: 1, name: "同步股票日线", status: "执行成功" },
            { id: 2, name: "同步指数成分", status: "等待处理" },
          ]}
        />
      </MantineProvider>,
    );

    const selectedCell = screen.getByText("同步指数成分");
    const selectedRow = selectedCell.closest("tr");
    expect(selectedRow).toHaveAttribute("data-selected", "true");

    fireEvent.click(selectedRow!);
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("renders empty state when rows are absent", () => {
    render(
      <MantineProvider theme={appTheme}>
        <DataTable
          columns={columns}
          emptyState={<div>当前没有任务</div>}
          getRowKey={(row) => row.id}
          rows={[]}
        />
      </MantineProvider>,
    );

    expect(screen.getByText("当前没有任务")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
