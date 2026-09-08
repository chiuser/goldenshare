import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WatchlistPage } from "./WatchlistPage";
import { group, item, page, rules } from "../../features/watchlist/test/watchlistFixtures";
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState({}, "", "/wealth/market/watchlist"); });
function server(mode: "success" | "unknown" = "success") {
  let added = false, failGroups = false, failMembership = false;
  let groups = [group(1, { memberCount: 1 }), group(2), group(3)];
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input)), method = init?.method ?? "GET", path = url.pathname;
    if (path.endsWith("/watchlist/groups") && method === "GET") return failGroups ? json({ code: "WL_QUERY_FAILED", message: "分组刷新失败" }, 500) : json({ groups, rules });
    if (path.endsWith("/watchlist/groups") && method === "POST") {
      const body = JSON.parse(String(init?.body)); const created = group(4, body); groups = [...groups, created]; return json({ group: created });
    }
    if (path.endsWith("/color")) {
      const id = Number(path.split("/").at(-2)); const body = JSON.parse(String(init?.body));
      groups = groups.map(g => g.id === id ? { ...g, color: body.color } : g); return json({ group: groups.find(g => g.id === id) });
    }
    if (method === "DELETE") {
      const id = Number(path.split("/").at(-1)), index = groups.findIndex(g => g.id === id);
      const nextGroupId = groups[index + 1]?.id ?? 1; groups = groups.filter(g => g.id !== id);
      return json({ deletedGroupId: id, deletedMemberCount: 0, nextGroupId });
    }
    if (path.endsWith("/search")) return json({ groupId: 1, keyword: "A", items: mode === "unknown" && added ? [] : [{ tsCode: "000002.SZ", name: "新股票", status: added ? "ADDED" : "AVAILABLE" }] });
    if (path.endsWith("/groups/1/items/000002.SZ")) {
      added = true; groups[0] = { ...groups[0], memberCount: 2 };
      return mode === "unknown" ? json({ code: "WL_WRITE_OUTCOME_UNKNOWN", message: "待确认" }, 503) : json({ groupId: 1, tsCode: "000002.SZ", isAdded: true, created: true, memberCount: 2 });
    }
    if (path.endsWith("/items")) {
      const id = Number(path.split("/").at(-2));
      return json(page(id === 1 ? added ? [item(2), item(1)] : [item(1)] : [], { group: groups.find(g => g.id === id) ?? group(id) }));
    }
    if (path.endsWith("/stocks/000002.SZ/groups")) return failMembership ? json({ code: "WL_QUERY_FAILED", message: "归属读取失败" }, 500) : json({ tsCode: "000002.SZ", isAdded: true, groups: [{ groupId: 1, name: "我的自选", isDefault: true, color: null, selected: true }] });
    return json({}, 503);
  });
  vi.stubGlobal("fetch", fetch);
  const calls = (suffix: string, method = "GET") => fetch.mock.calls.filter(([url, options]) => {
    const path = new URL(String(url)).pathname;
    return (suffix === "/groups" ? path === "/api/v1/wealth/market/watchlist/groups" : path.endsWith(suffix)) && (options?.method ?? "GET") === method;
  });
  return { fetch, calls, failGroups: (value: boolean) => { failGroups = value; }, failMembership: (value: boolean) => { failMembership = value; } };
}
async function openSearch() {
  fireEvent.click(screen.getByRole("button", { name: "+ 添加自选" }));
  fireEvent.change(screen.getByRole("textbox", { name: "搜索股票" }), { target: { value: "A" } });
  return screen.findByRole("button", { name: "添加 新股票 000002.SZ" });
}
describe("watchlist grouping page coordination", () => {
  it("retains the create draft when a definite limit failure is followed by a failed groups reread", async () => {
    const backend = server();
    const original = backend.fetch.getMockImplementation()!;
    backend.fetch.mockImplementation(async (input, init) => {
      if (init?.method === "POST") {
        backend.failGroups(true);
        return json({ code: "WL_GROUP_LIMIT_REACHED", message: "分组已达上限" }, 409);
      }
      return original(input, init);
    });
    render(<WatchlistPage />); await screen.findByRole("tab", { name: "我的自选" });
    fireEvent.click(screen.getByRole("button", { name: "+ 新建分组" }));
    fireEvent.change(screen.getByRole("textbox", { name: "分组名称" }), { target: { value: "成长" } });
    fireEvent.click(screen.getByRole("radio", { name: rules.palette[1] }));
    fireEvent.click(screen.getByRole("button", { name: "创建" }));
    await screen.findByText("自选分组暂不可用");
    backend.failGroups(false); fireEvent.click(screen.getByRole("button", { name: "重试读取" }));
    expect(await screen.findByRole("textbox", { name: "分组名称" })).toHaveValue("成长");
    expect(screen.getByRole("radio", { name: rules.palette[1] })).toBeChecked();
    expect(screen.getByRole("alert")).toHaveTextContent("分组已达上限");
    expect(backend.calls("/groups", "POST")).toHaveLength(1);
  });
  it("refreshes groups, sorted first page and search exactly once after one successful add", async () => {
    const backend = server(); render(<WatchlistPage />);
    await screen.findByRole("table", { name: "自选股票列表" });
    fireEvent.click(screen.getByRole("button", { name: /最新价/ }));
    await waitFor(() => expect(backend.calls("/groups/1/items")).toHaveLength(2));
    fireEvent.click(await openSearch());
    await screen.findByText("已添加到「我的自选」");
    await waitFor(() => expect(backend.calls("/search")).toHaveLength(2));
    expect(backend.calls("/groups", "GET")).toHaveLength(2);
    expect(backend.calls("/groups/1/items")).toHaveLength(3);
    expect(new URL(String(backend.calls("/groups/1/items").at(-1)?.[0])).searchParams.get("direction")).toBe("desc");
    expect(backend.calls("/groups/1/items/000002.SZ", "PUT")).toHaveLength(1);
    expect([...document.querySelectorAll("tbody .stock-code-column")].map(node => node.textContent)).toEqual(["000002.SZ", "000001.SZ"]);
  });
  it("auto-reconciles unknown add, falls back to single-stock membership when search omits it, and retries reads only", async () => {
    const backend = server("unknown"); render(<WatchlistPage />);
    await screen.findByRole("table", { name: "自选股票列表" });
    backend.failMembership(true); fireEvent.click(await openSearch());
    await waitFor(() => expect(backend.calls("/stocks/000002.SZ/groups")).toHaveLength(1));
    expect(screen.getByRole("textbox", { name: "搜索股票" })).toBeDisabled();
    expect(screen.queryByText("已添加到「我的自选」")).not.toBeInTheDocument();
    expect(backend.calls("/groups", "GET")).toHaveLength(2); expect(backend.calls("/groups/1/items")).toHaveLength(2); expect(backend.calls("/search")).toHaveLength(2);
    backend.failMembership(false);
    fireEvent.click(within(screen.getByRole("dialog", { name: "添加自选" })).getByRole("button", { name: "重试读取" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "搜索股票" })).toBeEnabled());
    expect(backend.calls("/groups/1/items/000002.SZ", "PUT")).toHaveLength(1);
    expect(backend.calls("/stocks/000002.SZ/groups")).toHaveLength(2);
    expect(screen.queryByText("已添加到「我的自选」")).not.toBeInTheDocument();
  });
  it("does not convert successful add into failure or replay PUT when groups refresh fails", async () => {
    const backend = server(); render(<WatchlistPage />);
    await screen.findByRole("table", { name: "自选股票列表" });
    const add = await openSearch(); backend.failGroups(true); fireEvent.click(add);
    await screen.findByText("添加已完成，列表刷新失败，请重试读取。");
    expect(screen.queryByText(/提交结果待确认/)).not.toBeInTheDocument();
    backend.failGroups(false); fireEvent.click(screen.getByRole("button", { name: "重试读取" }));
    await screen.findByRole("table", { name: "自选股票列表" });
    expect(backend.calls("/groups/1/items/000002.SZ", "PUT")).toHaveLength(1);
  });
  it("creates then selects the server group, recolors without selecting stocks and deletes only the current group", async () => {
    const backend = server(); render(<WatchlistPage />);
    await screen.findByRole("tab", { name: "我的自选" });
    fireEvent.click(screen.getByRole("button", { name: "+ 新建分组" }));
    fireEvent.change(screen.getByRole("textbox", { name: "分组名称" }), { target: { value: "  成长 " } });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "成长" })).toHaveAttribute("aria-selected", "true"));
    await screen.findByText("当前分组还没有股票");
    expect(backend.calls("/groups", "POST")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "操作" }));
    fireEvent.click(screen.getByRole("button", { name: "修改颜色" }));
    fireEvent.click(screen.getByRole("radio", { name: rules.palette[1] })); fireEvent.click(screen.getByRole("button", { name: "确认" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(backend.calls("/groups/4/color", "PATCH")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "编辑中" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "删除分组" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("0 只股票");
    expect(backend.calls("/groups/4", "DELETE")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "我的自选" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.queryByRole("tab", { name: "成长" })).not.toBeInTheDocument();
    expect(backend.calls("/groups/4", "DELETE")).toHaveLength(1); expect(screen.queryByRole("button", { name: "编辑中" })).not.toBeInTheDocument();
  });
});
