import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ShortcutBar } from "./ShortcutBar";
import type { ShortcutItem } from "./shortcutBarTypes";

const items: readonly ShortcutItem[] = [
  { key: "first", path: "/first", title: "第一项", description: "第一项说明", badge: "新" },
  { key: "second", path: "/second", title: "第二项", description: "第二项说明", disabled: true },
];

describe("ShortcutBar", () => {
  it("keeps the established inner structure and navigates from a native button", () => {
    const onNavigate = vi.fn();
    const { container } = render(<ShortcutBar activeKey="first" items={items} onNavigate={onNavigate} />);

    const first = screen.getByRole("button", { name: /第一项/ });
    expect(first).toHaveClass("shortcut-card", "selected");
    expect(first.querySelector(".shortcut-top .shortcut-title")).toHaveTextContent("第一项");
    expect(first.querySelector(".shortcut-desc")).toHaveTextContent("第一项说明");
    expect(container.querySelectorAll("article")).toHaveLength(0);

    fireEvent.click(first);
    expect(onNavigate).toHaveBeenCalledWith("/first");
  });

  it("does not navigate from a disabled item", () => {
    const onNavigate = vi.fn();
    render(<ShortcutBar activeKey={null} items={items} onNavigate={onNavigate} />);

    const second = screen.getByRole("button", { name: /第二项/ });
    expect(second).toBeDisabled();
    fireEvent.click(second);
    expect(onNavigate).not.toHaveBeenCalled();
  });
});
