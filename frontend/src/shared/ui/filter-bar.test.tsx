import { Button, MantineProvider, Select } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appTheme } from "../../app/theme";
import { FilterBar, FilterBarItem } from "./filter-bar";

describe("FilterBar", () => {
  it("renders filter controls and trailing actions", () => {
    render(
      <MantineProvider theme={appTheme}>
        <FilterBar
          actions={<Button variant="light">清空筛选</Button>}
        >
          <FilterBarItem>
            <Select label="当前状态" data={[{ value: "running", label: "执行中" }]} />
          </FilterBarItem>
          <FilterBarItem>
            <Select label="发起方式" data={[{ value: "manual", label: "手动" }]} />
          </FilterBarItem>
          <FilterBarItem>
            <Select label="任务名称" data={[{ value: "sync.daily", label: "股票日线" }]} />
          </FilterBarItem>
        </FilterBar>
      </MantineProvider>,
    );

    expect(screen.getByRole("textbox", { name: "当前状态" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "发起方式" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "任务名称" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "清空筛选" })).toBeInTheDocument();
  });
});
