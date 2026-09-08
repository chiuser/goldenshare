import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { group, item, rules } from "../test/watchlistFixtures";
import { WatchlistColorMarks } from "./WatchlistColorMarks";
import { WatchlistTabs } from "./WatchlistTabs";
import { WatchlistGroupTargetDialog } from "./WatchlistGroupTargetDialog";
import { CreateWatchlistGroupDialog } from "./CreateWatchlistGroupDialog";
import { WatchlistTable } from "./WatchlistTable";
import { buildWatchlistRow } from "../model/watchlistViewModelAdapter";
describe("watchlist grouping UI", () => {
  it("preserves each same-color segment, creation order and independent accessible tooltip", () => {
    const marks = [{
      groupId: 2,
      name: "成长",
      color: rules.palette[0]
    }, {
      groupId: 3,
      name: "观察",
      color: rules.palette[0]
    }];
    const {
      container,
      rerender
    } = render(<WatchlistColorMarks marks={marks} />);
    expect(screen.getByLabelText("属于分组：成长")).toHaveAttribute("title", "属于分组：成长");
    expect(screen.getByLabelText("属于分组：观察")).toHaveAttribute("title", "属于分组：观察");
    expect(container.firstElementChild).toHaveStyle({
      gridTemplateRows: "repeat(2, 1fr)"
    });
    expect([...container.querySelectorAll("[title]")].map(node => node.getAttribute("title"))).toEqual(["属于分组：成长", "属于分组：观察"]);
    rerender(<WatchlistColorMarks marks={[]} />);
    expect(container.querySelector("[title]")).toBeNull();
  });
  it("keeps default first and freezes noncurrent tabs and creation", () => {
    const onSelect = vi.fn();
    render(<WatchlistTabs groups={[group(), group(2)]} currentGroupId={1} locked canCreate onSelect={onSelect} onCreate={vi.fn()} />);
    expect(screen.getAllByRole("tab").map(node => node.textContent)).toEqual(["我的自选", "分组2"]);
    fireEvent.click(screen.getByRole("tab", {
      name: "分组2"
    }));
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("button", {
      name: "+ 新建分组"
    })).toBeDisabled();
  });
  it.each(["move", "add"] as const)("%s excludes current group and uses the approved selection cardinality", mode => {
    const confirm = vi.fn();
    render(<WatchlistGroupTargetDialog open locked={false} mode={mode} currentGroupId={1} groups={[group(), group(2), group(3)]} onConfirm={confirm} onCancel={vi.fn()} />);
    expect(screen.queryByLabelText("我的自选")).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "确认"
    })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("分组2"));
    fireEvent.click(screen.getByLabelText("分组3"));
    fireEvent.click(screen.getByRole("button", {
      name: "确认"
    }));
    expect(confirm).toHaveBeenCalledWith(mode === "move" ? [3] : [2, 3]);
  });
  it("trims creation, consumes server palette and keeps draft after refreshed limits", () => {
    const onConfirm = vi.fn();
    const props = {
      open: true,
      locked: false,
      groups: [group()],
      rules,
      onConfirm,
      onCancel: vi.fn()
    };
    const {
      rerender
    } = render(<CreateWatchlistGroupDialog {...props} />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: {
        value: "  成长  "
      }
    });
    fireEvent.click(screen.getByRole("radio", {
      name: rules.palette[1]
    }));
    rerender(<CreateWatchlistGroupDialog {...props} rules={{
      ...rules,
      palette: [...rules.palette]
    }} error="分组重名" />);
    expect(screen.getByRole("textbox")).toHaveValue("  成长  ");
    expect(screen.getByRole("radio", {
      name: rules.palette[1]
    })).toBeChecked();
    fireEvent.click(screen.getByRole("button", {
      name: "创建"
    }));
    expect(onConfirm).toHaveBeenCalledWith("成长", rules.palette[1]);
    rerender(<CreateWatchlistGroupDialog {...props} groups={Array.from({
      length: 10
    }, (_, i) => group(i + 1))} />);
    expect(screen.getByRole("button", {
      name: "创建"
    })).toBeDisabled();
  });
  it("renders eight sort controls and aria direction, with no operation column or select-all", () => {
    const onSort = vi.fn(),
      onSelect = vi.fn(),
      onToggle = vi.fn();
    render(<WatchlistTable rows={[buildWatchlistRow(item())]} editing selectedIds={new Set()} maxSelection={200} locked={false} sort={{
      sortBy: "price",
      direction: "desc"
    }} onSort={onSort} onToggle={onToggle} hasMore={false} loadingMore={false} loadMoreError={null} scrollResetKey={0} onLoadMore={vi.fn()} onRetryMore={vi.fn()} onSelect={onSelect} />);
    expect(document.querySelectorAll("th[aria-sort]")).toHaveLength(8);
    expect(document.querySelector('th[aria-sort="descending"]')).toHaveTextContent("最新价");
    expect(document.querySelector("thead input")).toBeNull();
    expect(document.querySelector(".action-column")).toBeNull();
    fireEvent.click(screen.getByRole("button", {
      name: /最新价/
    }));
    expect(onSort).toHaveBeenCalledWith("price");
    fireEvent.click(screen.getByRole("button", {
      name: "000001.SZ"
    }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onToggle).toHaveBeenCalledTimes(2);
  });
});
