import { MantineProvider } from "@mantine/core";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { appTheme } from "../../app/theme";
import { OpsEnumMultiSelect } from "./ops-enum-multi-select";


describe("OpsEnumMultiSelect", () => {
  it("uses a virtual all option while emitting only real enum values", () => {
    const onChange = vi.fn();
    const options = ["1", "2", "3"];
    render(
      <MantineProvider theme={appTheme}>
        <OpsEnumMultiSelect
          label="报表类型"
          options={options}
          optionLabels={{ "1": "合并报表", "2": "单季合并", "3": "调整单季合并表" }}
          value={options}
          onChange={onChange}
          selectAllEnabled
        />
      </MantineProvider>,
    );

    expect(screen.getByRole("checkbox", { name: "全部" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "合并报表" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "全部" }));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("selecting all emits the complete real option list", () => {
    const onChange = vi.fn();
    render(
      <MantineProvider theme={appTheme}>
        <OpsEnumMultiSelect
          label="报表类型"
          options={["1", "2"]}
          value={[]}
          onChange={onChange}
          selectAllEnabled
        />
      </MantineProvider>,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "全部" }));
    expect(onChange).toHaveBeenCalledWith(["1", "2"]);
  });
});
