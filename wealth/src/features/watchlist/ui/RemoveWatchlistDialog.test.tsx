import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RemoveWatchlistDialog } from "./RemoveWatchlistDialog";

describe("centered removal dialog", () => {
  it("uses a modal without anchor coordinates and stops inner click propagation", () => {
    const onCancel = vi.fn(),
      onConfirm = vi.fn(),
      parent = vi.fn();
    render(
      <div onClick={parent}>
        <RemoveWatchlistDialog
          open
          pending={false}
          stock={{ tsCode: "000001.SZ", name: "平安银行" }}
          onCancel={onCancel}
          onConfirm={onConfirm}
        />
      </div>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveClass("watchlist-remove-dialog");
    expect(dialog).not.toHaveAttribute("style");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog.parentElement).toBe(document.body);
    fireEvent.click(screen.getByRole("heading"));
    expect(onCancel).not.toHaveBeenCalled();
    expect(parent).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认移除" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent(
      dialog,
      new Event("cancel", { bubbles: false, cancelable: true }),
    );
    fireEvent.click(dialog);
    expect(onCancel).toHaveBeenCalledTimes(3);
  });
  it("locks confirm, cancel, Escape and backdrop while pending, and keeps errors local", () => {
    const onCancel = vi.fn(),
      onConfirm = vi.fn();
    render(
      <RemoveWatchlistDialog
        open
        pending
        stock={{ tsCode: "000001.SZ", name: "平安银行" }}
        error="移除失败"
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
    );
    expect(screen.getByRole("button", { name: "处理中" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();
    fireEvent.click(screen.getByRole("dialog"));
    fireEvent(
      screen.getByRole("dialog"),
      new Event("cancel", { cancelable: true }),
    );
    expect(onCancel).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("移除失败");
  });
});
