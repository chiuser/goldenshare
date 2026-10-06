import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { dataCenterApi } from "../api/dataCenterApi";
import { HistoryPanel } from "./HistoryPanel";
afterEach(() => vi.restoreAllMocks());
const history = (id: string, nextCursor: string | null = null) => ({ items: [{ runId: id, rootRunId: id, retryOfRunId: null, batchKind: "date" as const, phase: "completed", createdAt: "2026-10-06T02:00:00Z", startDate: "2026-09-30", endDate: "2026-09-30", total: 1, succeeded: 1, reused: 0, failed: 0 }], nextCursor, currentRunId: null });
it("latest reloads page one and selects its current server result", async () => {
  vi.spyOn(dataCenterApi, "history").mockResolvedValueOnce(history("first", "next")).mockResolvedValueOnce(history("older")).mockResolvedValueOnce(history("newest"));
  const select = vi.fn(); render(<HistoryPanel revision={0} onSelect={select} />);
  await screen.findByRole("button", { name: "查看详情" });
  fireEvent.click(screen.getByRole("button", { name: "下一页" }));
  await screen.findByText(/第 2 页/);
  await waitFor(() => expect(screen.getByRole("button", { name: "查看最近任务" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "查看最近任务" }));
  await waitFor(() => expect(select).toHaveBeenCalledWith("newest"));
  expect(select).not.toHaveBeenCalledWith("older");
});
