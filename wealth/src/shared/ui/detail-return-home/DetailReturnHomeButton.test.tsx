import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DetailReturnHomeButton } from "./DetailReturnHomeButton";

describe("DetailReturnHomeButton", () => {
  it("uses the approved label and delegates navigation to the page", () => {
    const onReturnHome = vi.fn();
    render(<DetailReturnHomeButton onReturnHome={onReturnHome} />);

    fireEvent.click(screen.getByRole("button", { name: "返回首页" }));

    expect(onReturnHome).toHaveBeenCalledOnce();
    expect(screen.getByText("←")).toHaveAttribute("aria-hidden", "true");
  });
});
