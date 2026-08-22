import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PageBreadcrumb } from "./PageBreadcrumb";

describe("PageBreadcrumb", () => {
  it("renders the two-level Wealth exploration hierarchy using the shared DOM", () => {
    const onNavigate = vi.fn();
    render(
      <PageBreadcrumb
        items={[
          { label: "财势乾坤", path: "/wealth/market/overview" },
          { label: "财势探查" },
        ]}
        onNavigate={onNavigate}
        sessionStatus="CLOSED"
      />,
    );

    screen.getByRole("button", { name: "财势乾坤" }).click();
    expect(screen.getByText("财势探查")).toHaveClass("current");
    expect(screen.getByText("已收盘")).toBeInTheDocument();
    expect(onNavigate).toHaveBeenCalledWith("/wealth/market/overview");
  });
});
