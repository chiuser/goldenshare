import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useDownloads } from "./useDownloads";
import { dataCenterApi } from "../api/dataCenterApi";
import { contextFixture, taskFixture } from "./fixtures";
import type { Preview } from "../api/contracts";
afterEach(() => vi.restoreAllMocks());
it("continuing the same stopped run restarts sequential observation", async () => {
  const stopped = { ...taskFixture, phase: "cancelled" as const, actions: { ...taskFixture.actions, canContinue: true } };
  const read = vi.spyOn(dataCenterApi, "task").mockResolvedValueOnce(stopped).mockResolvedValue({ ...taskFixture, phase: "completed" });
  vi.spyOn(dataCenterApi, "continue").mockResolvedValue(taskFixture);
  const { result } = renderHook(() => useDownloads(contextFixture, true, taskFixture.runId, vi.fn(), vi.fn()));
  await waitFor(() => expect(result.current.run?.phase).toBe("cancelled"));
  await act(async () => result.current.continueRun());
  await waitFor(() => expect(result.current.run?.phase).toBe("completed"));
  expect(read).toHaveBeenCalledTimes(2);
});
it("unknown command outcome retries with the same key and no automatic POST", async () => {
  const preview = { previewId: "preview", state: "ready", canStart: true } as Preview;
  vi.spyOn(dataCenterApi, "createPreview").mockResolvedValue(preview);
  const send = vi.spyOn(dataCenterApi, "createRun").mockRejectedValueOnce(new Error("connection lost")).mockResolvedValue(taskFixture);
  const choose = vi.fn(); const { result } = renderHook(() => useDownloads(contextFixture, true, null, choose, vi.fn()));
  act(() => { result.current.setStart("2026-09-30"); result.current.setEnd("2026-09-30"); result.current.setInterval("0"); });
  await act(async () => result.current.prepare());
  await act(async () => result.current.start()); expect(result.current.unresolvedCommand).toBe(true); expect(send).toHaveBeenCalledTimes(1);
  await act(async () => result.current.start()); expect(send).toHaveBeenCalledTimes(1);
  await act(async () => result.current.retryCommand()); expect(send).toHaveBeenCalledTimes(2);
  expect(send.mock.calls[0][1]).toBe(send.mock.calls[1][1]); expect(choose).toHaveBeenCalledWith(taskFixture.runId);
});
it("invalid ranges never preview; changing dates invalidates confirmation", async () => {
  const send = vi.spyOn(dataCenterApi, "createPreview").mockResolvedValue({ previewId: "p", state: "ready" } as Preview);
  const { result } = renderHook(() => useDownloads(contextFixture, false, null, vi.fn(), vi.fn()));
  await act(async () => result.current.prepare()); expect(send).not.toHaveBeenCalled();
  act(() => { result.current.setStart("2026-10-01"); result.current.setEnd("2026-09-30"); });
  await act(async () => result.current.prepare()); expect(send).not.toHaveBeenCalled();
  act(() => result.current.setStart("2026-09-30")); await act(async () => result.current.prepare()); expect(result.current.preview?.previewId).toBe("p");
  act(() => result.current.setInterval("0")); expect(result.current.preview).toBeNull();
});
it("unmounting current observation never stops or continues the backend run", async () => {
  vi.spyOn(dataCenterApi, "task").mockResolvedValue(taskFixture); const stop = vi.spyOn(dataCenterApi, "stop"); const resume = vi.spyOn(dataCenterApi, "continue");
  const { result, unmount } = renderHook(() => useDownloads(contextFixture, true, taskFixture.runId, vi.fn(), vi.fn()));
  await waitFor(() => expect(result.current.run?.processed).toBe(320)); unmount(); expect(stop).not.toHaveBeenCalled(); expect(resume).not.toHaveBeenCalled();
});
