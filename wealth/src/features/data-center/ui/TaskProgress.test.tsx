import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { taskFixture } from "../model/fixtures";
import { TaskProgress } from "./TaskProgress";
import { StopDialog } from "./StopDialog";
it("legacy terminal results explain why exact recovery is unavailable", () => {
  const reason = "历史任务不支持精确恢复，可新建日期下载";
  render(<TaskProgress task={{ ...taskFixture, phase: "interrupted", actions: { ...taskFixture.actions, canStop: false, canContinue: false, reason } }} busy={false} error={null} onStop={vi.fn()} />);
  expect(screen.getByText(reason)).toBeInTheDocument(); expect(screen.queryByRole("button", { name: "停止任务" })).toBeNull();
});
it("stopping cannot submit another stop even if the snapshot permits stop", () => {
  render(<TaskProgress task={{ ...taskFixture, phase: "stopping", actions: { ...taskFixture.actions, canStop: true } }} busy={false} error={null} onStop={vi.fn()} />);
  expect(screen.getByRole("button", { name: "停止中…" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "停止任务" })).toBeNull();
});
it("100 percent containing failures remains partial_failed, with missing URL separate", () => {
  render(<TaskProgress task={{ ...taskFixture, phase: "partial_failed", processed: 1000, percent: 100, remaining: 0 }} busy={false} error={null} onStop={vi.fn()} />);
  expect(screen.getByRole("heading", { name: "已结束，存在失败项" })).toBeInTheDocument(); expect(screen.queryByRole("heading", { name: "全部成功" })).toBeNull();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100"); expect(screen.getByText("无 URL 公告")).toBeInTheDocument();
});
it("preparation never shows a fake percentage or ETA", () => {
  render(<TaskProgress task={{ ...taskFixture, phase: "preparing", total: null, percent: null, remaining: null }} busy={false} error={null} onStop={vi.fn()} />);
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow"); expect(screen.getByText(/总量尚未确定/)).toBeInTheDocument(); expect(screen.getByText(/剩余时间暂无法估算/)).toBeInTheDocument();
});
it("unknown file length and observation failure are distinct from execution failure", () => {
  render(<TaskProgress task={{ ...taskFixture, current: { artifactKey: "a", annDate: "2026-09-30", tsCode: "000001.SZ", companyName: "平安银行", title: "董事会", attemptNumber: 2, maxAttempts: 3, bytesReceived: 1234, bytesTotal: null, transferState: "receiving" } }} busy={false} error="连接状态暂不可获取" onStop={vi.fn()} />);
  expect(screen.getByText(/文件总字节未知/)).toBeInTheDocument(); expect(screen.getByRole("heading", { name: "正在下载" })).toBeInTheDocument(); expect(screen.getByText(/执行阶段尚无法重新确认/)).toBeInTheDocument();
});
it("stop is a concrete confirmed action, cancel does not submit", () => {
  const cancel = vi.fn(), confirm = vi.fn(); render(<StopDialog task={taskFixture} busy={false} onCancel={cancel} onConfirm={confirm} />);
  fireEvent.click(screen.getByRole("button", { name: "继续下载" })); expect(cancel).toHaveBeenCalledTimes(1); expect(confirm).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole("button", { name: "确认停止" })); expect(confirm).toHaveBeenCalledTimes(1);
});
