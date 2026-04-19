import { Button, MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appTheme } from "../../app/theme";
import { PageHeader } from "./page-header";

describe("PageHeader", () => {
  it("keeps heading semantics and renders actions", () => {
    render(
      <MantineProvider theme={appTheme}>
        <PageHeader
          title="平台检查"
          description="用于确认当前平台健康状态。"
          action={<Button>刷新</Button>}
        />
      </MantineProvider>,
    );

    expect(screen.getByRole("heading", { level: 2, name: "平台检查" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新" })).toBeInTheDocument();
  });
});
