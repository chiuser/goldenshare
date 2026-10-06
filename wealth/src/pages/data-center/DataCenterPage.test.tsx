import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { dataCenterApi } from "../../features/data-center/api/dataCenterApi";
import { DataCenterPage } from "./DataCenterPage";
import { readAnnouncementRoute } from "./AnnouncementsPage";
vi.mock("./DataCenterShell", () => ({ DataCenterShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
afterEach(() => vi.restoreAllMocks());
it("Prod homepage has no announcement card or placeholder", async () => {
  vi.spyOn(dataCenterApi, "modules").mockResolvedValue({ modules: [] }); render(<DataCenterPage />);
  expect(await screen.findByText("当前暂无可用数据模块")).toBeInTheDocument(); expect(screen.queryByRole("button", { name: /上市公司公告/ })).toBeNull();
});
it("local capability card remains visible even before any volume check", async () => {
  vi.spyOn(dataCenterApi, "modules").mockResolvedValue({ modules: [{ moduleKey: "announcements", title: "上市公司公告", description: "查询公告", path: "/wealth/data-center/announcements", badge: "本地" }] }); render(<DataCenterPage />);
  expect(await screen.findByRole("button", { name: /上市公司公告/ })).toBeInTheDocument();
});
it("failed capability read is not a zero module empty state", async () => {
  vi.spyOn(dataCenterApi, "modules").mockRejectedValue(new Error("模块读取失败")); render(<DataCenterPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("模块读取失败"); expect(screen.queryByText("当前暂无可用数据模块")).toBeNull();
});
it("defaults to query, validates unknown tabs and preserves selected run separately", () => {
  expect(readAnnouncementRoute("")).toEqual({ tab: "query", runId: null, invalidTab: false }); expect(readAnnouncementRoute("?tab=other&runId=abc").invalidTab).toBe(true); expect(readAnnouncementRoute("?tab=downloads&runId=abc")).toEqual({ tab: "downloads", runId: "abc", invalidTab: false });
});
