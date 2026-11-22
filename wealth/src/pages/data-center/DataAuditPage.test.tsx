import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dataAuditApi, type AuditDay, type AuditRow } from "../../features/data-center/api/dataAuditApi";
import { DataAuditPage } from "./DataAuditPage";

vi.mock("./DataCenterShell", () => ({ DataCenterShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));

const DAY = "2026-11-20";
const RUN = "de893284-eabf-48db-a3d2-17f5ba637a8b";
const checked = "2026-11-21T00:12:00+08:00";
const reason = { code: "check_passed", message: "现有生产 Check 通过" };

function row(name: string, status: AuditRow["completeness"]["status"], update: AuditRow["update"]["status"]): AuditRow {
  return {
    dataset_name: name, layer: "raw",
    scope: { asset_key: name, business_date: DAY, partition_key: DAY, as_of_date: DAY, frequency: "日更", coverage_scope: "dataset" },
    update: { status: update, expected_date: DAY, deadline_at: null, published_at: checked, reason },
    completeness: { status, reason, checked_at: checked, components: [] },
  };
}

const ready: AuditDay = {
  state: "ready", business_date: DAY, summary_run_id: RUN, observed_at: checked, generated_at: checked,
  summary: { complete: 1, gap: 1, pending: 1, not_applicable: 0 },
  rows: [
    row("上交所交易日历", "complete", "updated"),
    row("ETF 日线行情", "gap", "updated"),
    row("股票日线九转", "pending", "overdue"),
  ],
};

describe("local data audit", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(checked));
    vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("filters independently, resets the update filter from the summary, and pins details", async () => {
    vi.spyOn(dataAuditApi, "day").mockResolvedValue(ready);
    const detail = vi.spyOn(dataAuditApi, "detail").mockResolvedValue({
      ...ready.rows[1],
      version: { target_version: "article-version", inputs: [], rule_version: "test-rule" },
      completeness: {
        ...ready.rows[1].completeness, expected_count: 23, actual_count: 22,
        missing_count: 1, extra_count: 0, evidence: [], samples: [], exceptions: [],
      },
    });
    render(<DataAuditPage />);
    const table = await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("更新状态"), { target: { value: "overdue" } });
    expect(within(table).queryByText("ETF 日线行情")).toBeNull();
    fireEvent.change(screen.getByLabelText("齐备状态"), { target: { value: "gap" } });
    expect(screen.getByText("没有符合筛选条件的数据集")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "已确认缺口 1" }));
    expect(screen.getByLabelText("更新状态")).toHaveValue("");
    expect(screen.getByLabelText("业务日期")).toHaveValue(DAY);
    expect(screen.getByText("ETF 日线行情")).toBeInTheDocument();
    expect(screen.queryByText("股票日线九转")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "查看ETF 日线行情" }));
    expect(await screen.findByText("article-version")).toBeInTheDocument();
    expect(detail).toHaveBeenCalledWith(DAY, "ETF 日线行情", RUN, expect.any(AbortSignal));
    expect(screen.queryByRole("button", { name: "独立审计" })).toBeNull();
  });

  it("retains same-day results while offline and discards stale responses after a date change", async () => {
    const offline = { ...ready, state: "unavailable" as const, summary_run_id: null, rows: [] };
    let finishOld!: (value: AuditDay) => void;
    const oldRequest = new Promise<AuditDay>((resolve) => { finishOld = resolve; });
    const api = vi.spyOn(dataAuditApi, "day").mockResolvedValueOnce(ready)
      .mockResolvedValueOnce(offline).mockReturnValueOnce(oldRequest)
      .mockResolvedValueOnce({ ...offline, business_date: "2026-11-19", state: "not_generated" });
    render(<DataAuditPage />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("当前显示");
    expect(screen.getByRole("table")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    const oldSignal = api.mock.calls[2][1];
    fireEvent.change(screen.getByLabelText("业务日期"), { target: { value: "2026-11-19" } });
    expect(oldSignal.aborted).toBe(true);
    expect(await screen.findByText("所选日尚未生成每日总结")).toBeInTheDocument();
    await act(async () => finishOld(ready));
    expect(screen.queryByRole("table")).toBeNull();
  });
});
