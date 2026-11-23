import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  dataAuditApi, DC_CLASSIFICATION_RAW, DC_CLASSIFICATION_SILVER, type AuditBoardReview,
  type AuditBoardRun, type AuditDay, type AuditRow,
} from "../../features/data-center/api/dataAuditApi";
import { clientPolicy } from "../../features/data-center/api/clientPolicy";
import { DataCenterApiError } from "../../features/data-center/api/dataCenterApi";
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

const rawClassification = boardRow(DC_CLASSIFICATION_RAW, "raw");
const silverClassification = boardRow(DC_CLASSIFICATION_SILVER, "silver");
const reference = { business_date: "2026-11-19", version: "standard-reference", boards: [
  { category: "概念板块", code: "BK001.DC", name: "减少示例" },
  { category: "行业板块", code: "BK003.DC", name: "行业示例" },
] };
const candidate = { category: "概念板块", code: "BK002.DC", name: "新增示例" };
const review: AuditBoardReview = {
  business_date: DAY, review_version: "review-01", raw_run_id: RUN, state: "pending", reason: "manual_review",
  can_confirm: true, reference, current: [candidate, reference.boards[1]], added: [candidate],
  removed: [reference.boards[0]], standard: null, recheck: null,
};

function boardRow(key: string, layer: string): AuditRow {
  const base = row("东方财富板块分类", "pending", "updated");
  return { ...base, layer, scope: { ...base.scope, asset_key: key }, completeness: {
    ...base.completeness, components: [{ name: "东方财富概念板块", status: "pending", reason }],
  } };
}

async function openBoard(layer: "Raw" | "Silver" = "Raw") {
  await screen.findByRole("table");
  const button = screen.getAllByRole("button", { name: "查看东方财富概念板块" })[layer === "Raw" ? 0 : 1];
  fireEvent.click(button);
  return screen.findByRole("dialog", { name: "东方财富概念板块名单核查" });
}

describe("东方财富概念板块名单核查", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(checked));
    vi.spyOn(dataAuditApi, "day").mockResolvedValue({
      ...ready, can_operate: true, rows: [rawClassification, silverClassification],
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("loads the selected Silver board standard and exposes read-only reference and differences", async () => {
    const read = vi.spyOn(dataAuditApi, "boardStandard").mockResolvedValue({ ...review, can_confirm: false });
    render(<DataAuditPage />);
    const dialog = within(await openBoard("Silver"));
    expect(await dialog.findByText("新增示例")).toBeInTheDocument();
    expect(read).toHaveBeenCalledWith(DAY, DC_CLASSIFICATION_SILVER, expect.any(AbortSignal));
    expect(dialog.queryByRole("button", { name: "核查 Tushare" })).not.toBeInTheDocument();
    expect(dialog.queryByRole("button", { name: "确认并生成标准集" })).not.toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: "查看参照标准集" }));
    expect(dialog.getByRole("heading", { name: "参照标准集 · 2026-11-19" })).toBeInTheDocument();
    expect(dialog.getByText("减少示例")).toBeInTheDocument();
    expect(dialog.queryByText("行业示例")).not.toBeInTheDocument();
  });

  it("shows industry and region changes for confirmation when the concept list is unchanged", async () => {
    const industry = reference.boards[1];
    const region = { category: "地域板块", code: "BK004.DC", name: "地域示例" };
    vi.spyOn(dataAuditApi, "boardStandard").mockResolvedValue({
      ...review, current: [reference.boards[0], region], added: [region], removed: [industry],
    });
    render(<DataAuditPage />);
    const dialog = within(await openBoard());
    expect(await dialog.findByRole("row", { name: "地域板块 BK004.DC 地域示例 新增" })).toBeInTheDocument();
    expect(dialog.getByRole("row", { name: "行业板块 BK003.DC 行业示例 减少" })).toBeInTheDocument();
    expect(dialog.getByText("无概念板块增减")).toBeInTheDocument();
    expect(dialog.getByRole("button", { name: "核查 Tushare" })).toBeDisabled();
    expect(dialog.getByRole("button", { name: "确认并生成标准集" })).toBeEnabled();
  });

  it("hides write actions without admin permission and shows a missing reference distinctly", async () => {
    vi.mocked(dataAuditApi.day).mockResolvedValue({ ...ready, can_operate: false, rows: [rawClassification] });
    vi.spyOn(dataAuditApi, "boardStandard").mockResolvedValue({
      ...review, review_version: null, state: "reference_missing", can_confirm: false, reference: null,
    });
    render(<DataAuditPage />);
    const dialog = within(await openBoard());
    expect(await dialog.findByText("参照标准集缺失")).toBeInTheDocument();
    expect(dialog.queryByRole("button", { name: "核查 Tushare" })).not.toBeInTheDocument();
    expect(dialog.queryByRole("button", { name: "确认并生成标准集" })).not.toBeInTheDocument();
  });

  it("locks all exit and action paths and blocks confirm when the source proves a gap", async () => {
    vi.spyOn(dataAuditApi, "boardStandard").mockResolvedValue(review);
    let finish!: (run: AuditBoardRun) => void;
    const submit = vi.spyOn(dataAuditApi, "boardRecheck").mockImplementation(() =>
      new Promise<AuditBoardRun>((resolve) => { finish = resolve; }));
    const confirm = vi.spyOn(dataAuditApi, "boardConfirm");
    render(<DataAuditPage />);
    const modal = await openBoard();
    const dialog = within(modal);
    fireEvent.click(await dialog.findByRole("button", { name: "核查 Tushare" }));
    expect(dialog.getByRole("status")).toHaveTextContent("正在核查 Tushare");
    expect(dialog.getByRole("status")).toHaveTextContent("2 个板块");
    for (const name of ["核查 Tushare", "查看参照标准集", "确认并生成标准集", "取消", "关闭"]) {
      const button = dialog.getByRole("button", { name });
      expect(button).toBeDisabled();
      fireEvent.click(button);
    }
    const cancel = new Event("cancel", { cancelable: true });
    fireEvent(modal, cancel);
    fireEvent.click(modal, { clientX: -1, clientY: -1 });
    expect(cancel.defaultPrevented).toBe(true);
    expect(modal).toHaveAttribute("open");
    expect(submit).toHaveBeenCalledExactlyOnceWith(DAY, "review-01", undefined, expect.any(AbortSignal));
    await act(async () => finish({ run_id: RUN, status: "SUCCESS", result: {
      business_date: DAY, review_version: "review-01", has_confirmed_gap: true, results: [{
        code: "BK001.DC", confirmed_gap: true, classification: { status: "success" }, member: { status: "not_returned" },
      }],
    } }));
    expect(dialog.getByText("已确认缺口")).toBeInTheDocument();
    expect(dialog.getByText("源端有，本地缺少")).toBeInTheDocument();
    expect(dialog.getByText("本次成分为空")).toBeInTheDocument();
    expect(dialog.getByRole("button", { name: "确认并生成标准集" })).toBeDisabled();
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(dialog.getByRole("button", { name: "关闭" }));
    expect(modal).not.toBeInTheDocument();
  });

  it("preserves differences and passes only the previous recheck run to the failed-item retry", async () => {
    const prior: AuditBoardReview["recheck"] = {
      business_date: DAY, review_version: "review-01", run_id: RUN, has_confirmed_gap: false, results: [{
        code: "BK001.DC", classification: { status: "not_returned" }, member: { status: "failed", message: "成分请求失败" },
      }],
    };
    vi.spyOn(dataAuditApi, "boardStandard").mockResolvedValue({ ...review, recheck: prior });
    const submit = vi.spyOn(dataAuditApi, "boardRecheck").mockRejectedValue(new DataCenterApiError(503, "", "暂时无法提交本机 DG 核查"));
    render(<DataAuditPage />);
    const dialog = within(await openBoard());
    expect(await dialog.findByText("源端本次未返回")).toBeInTheDocument();
    expect(dialog.getByText("成分请求失败")).toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: "重试失败项" }));
    expect(await dialog.findByRole("alert")).toHaveTextContent("暂时无法提交本机 DG 核查");
    expect(dialog.getByText("减少示例")).toBeInTheDocument();
    expect(dialog.getByRole("button", { name: "关闭" })).toBeEnabled();
    expect(submit).toHaveBeenCalledExactlyOnceWith(DAY, "review-01", RUN, expect.any(AbortSignal));
  });

  it("unlocks at the server deadline and reads the same run again without resubmitting", async () => {
    const deadline = new Date(Date.now() + 1000).toISOString();
    const read = vi.spyOn(dataAuditApi, "boardStandard").mockResolvedValue(review);
    const submit = vi.spyOn(dataAuditApi, "boardRecheck").mockResolvedValue({ run_id: RUN, status: "QUEUED", deadline });
    const run = vi.spyOn(dataAuditApi, "boardRun")
      .mockResolvedValueOnce({ run_id: RUN, status: "FAILURE", error: { code: "board_run_failed", message: "核查未完成" } });
    render(<DataAuditPage />);
    const dialog = within(await openBoard());
    const button = await dialog.findByRole("button", { name: "核查 Tushare" });
    vi.useRealTimers();
    vi.useFakeTimers();
    vi.setSystemTime(new Date(checked));
    await act(async () => fireEvent.click(button));
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(dialog.getByRole("alert")).toHaveTextContent("已到截止时间");
    expect(dialog.getByRole("button", { name: "关闭" })).toBeEnabled();
    expect(dialog.getByRole("button", { name: "确认并生成标准集" })).toBeDisabled();
    await act(async () => fireEvent.click(dialog.getByRole("button", { name: "重新读取任务状态" })));
    expect(dialog.getByRole("alert")).toHaveTextContent("核查未完成");
    expect(submit).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledExactlyOnceWith(RUN, expect.any(AbortSignal));
    expect(read).toHaveBeenCalledTimes(2);
  });

  it.each(["terminal", "deadline"])("keeps the dialog locked after a status GET 503 until %s", async (end) => {
    const pollMs = clientPolicy.defaultPollSeconds * 1000;
    const retryMs = clientPolicy.readRetrySeconds * 1000;
    const deadlineMs = pollMs + retryMs + (end === "terminal" ? pollMs * 2 : pollMs / 2);
    const deadline = new Date(Date.now() + deadlineMs).toISOString();
    vi.spyOn(dataAuditApi, "boardStandard").mockResolvedValue(review);
    const submit = vi.spyOn(dataAuditApi, "boardRecheck").mockResolvedValue({ run_id: RUN, status: "QUEUED", deadline });
    const run = vi.spyOn(dataAuditApi, "boardRun")
      .mockRejectedValueOnce(new DataCenterApiError(503, "board_dg_unavailable", "暂时无法读取任务状态"))
      .mockResolvedValueOnce({ run_id: RUN, status: "STARTED", deadline: new Date(Date.now() + deadlineMs + pollMs).toISOString() })
      .mockResolvedValueOnce({ run_id: RUN, status: "SUCCESS" });
    render(<DataAuditPage />);
    const modal = await openBoard();
    const dialog = within(modal);
    const recheck = await dialog.findByRole("button", { name: "核查 Tushare" });
    vi.useRealTimers();
    vi.useFakeTimers();
    vi.setSystemTime(new Date(checked));
    await act(async () => fireEvent.click(recheck));
    await act(async () => vi.advanceTimersByTimeAsync(pollMs));
    expect(run).toHaveBeenCalledTimes(1);
    expect(dialog.getByRole("status")).toHaveTextContent("正在核查 Tushare");
    expect(recheck).toBeDisabled();
    expect(dialog.getByRole("button", { name: "关闭" })).toBeDisabled();
    expect(dialog.getByRole("button", { name: "确认并生成标准集" })).toBeDisabled();
    fireEvent(modal, new Event("cancel", { cancelable: true }));
    fireEvent.click(modal, { clientX: -1, clientY: -1 });
    expect(modal).toHaveAttribute("open");
    await act(async () => vi.advanceTimersByTimeAsync(retryMs));
    expect(run).toHaveBeenCalledTimes(2);
    expect(dialog.getByRole("button", { name: "关闭" })).toBeDisabled();

    await act(async () => vi.advanceTimersByTimeAsync(end === "terminal" ? pollMs : pollMs / 2));
    expect(dialog.getByRole("button", { name: "关闭" })).toBeEnabled();
    if (end === "deadline") {
      expect(dialog.getByRole("alert")).toHaveTextContent("已到截止时间");
      expect(run).toHaveBeenCalledTimes(2);
    } else {
      expect(dialog.queryByRole("alert")).not.toBeInTheDocument();
      expect(run).toHaveBeenCalledTimes(3);
    }
    expect(submit).toHaveBeenCalledTimes(1);
    expect(run.mock.calls.every(([runId]) => runId === RUN)).toBe(true);
  });

  it("keeps an accepted recheck locked through the actual status request timeout and a network failure", async () => {
    const pollMs = clientPolicy.defaultPollSeconds * 1000;
    const requestMs = clientPolicy.requestSeconds * 1000;
    const retryMs = clientPolicy.readRetrySeconds * 1000;
    const deadline = new Date(Date.now() + pollMs * 2 + requestMs + retryMs * 2).toISOString();
    vi.spyOn(dataAuditApi, "boardStandard").mockResolvedValue(review);
    const submit = vi.spyOn(dataAuditApi, "boardRecheck").mockResolvedValue({ run_id: RUN, status: "QUEUED", deadline });
    const fetch = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce((_input, init) => new Promise<Response>((_, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      }))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(Response.json({ run_id: RUN, status: "SUCCESS" }));
    render(<DataAuditPage />);
    const dialog = within(await openBoard());
    const recheck = await dialog.findByRole("button", { name: "核查 Tushare" });
    vi.useRealTimers();
    vi.useFakeTimers();
    vi.setSystemTime(new Date(checked));
    await act(async () => fireEvent.click(recheck));

    await act(async () => vi.advanceTimersByTimeAsync(pollMs + requestMs));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(dialog.getByRole("button", { name: "关闭" })).toBeDisabled();
    await act(async () => vi.advanceTimersByTimeAsync(retryMs));
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(dialog.getByRole("status")).toHaveTextContent("正在核查 Tushare");
    expect(dialog.getByRole("button", { name: "确认并生成标准集" })).toBeDisabled();

    await act(async () => vi.advanceTimersByTimeAsync(retryMs));
    expect(dialog.getByRole("button", { name: "关闭" })).toBeEnabled();
    expect(dialog.queryByRole("alert")).not.toBeInTheDocument();
    expect(submit).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(
      Array(3).fill(`/api/v1/wealth/data-center/data-audit/runs/${RUN}`),
    );
  });

  it("unlocks a confirmation without a deadline after a status GET 503", async () => {
    vi.spyOn(dataAuditApi, "boardStandard").mockResolvedValue(review);
    const submit = vi.spyOn(dataAuditApi, "boardConfirm").mockResolvedValue({ run_id: RUN, status: "QUEUED" });
    const run = vi.spyOn(dataAuditApi, "boardRun")
      .mockRejectedValue(new DataCenterApiError(503, "board_dg_unavailable", "暂时无法读取任务状态"));
    render(<DataAuditPage />);
    const dialog = within(await openBoard());
    const confirm = await dialog.findByRole("button", { name: "确认并生成标准集" });
    vi.useRealTimers();
    vi.useFakeTimers();
    vi.setSystemTime(new Date(checked));
    await act(async () => fireEvent.click(confirm));
    await act(async () => vi.advanceTimersByTimeAsync(clientPolicy.defaultPollSeconds * 1000));
    expect(dialog.getByRole("alert")).toHaveTextContent("暂时无法读取任务状态");
    expect(dialog.getByRole("button", { name: "关闭" })).toBeEnabled();
    expect(dialog.getByRole("button", { name: "重新读取任务状态" })).toBeEnabled();
    await act(async () => vi.advanceTimersByTimeAsync(clientPolicy.readRetrySeconds * 1000));
    expect(submit).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledExactlyOnceWith(RUN, expect.any(AbortSignal));
  });

  it("requires a new review after a stale version is rejected", async () => {
    vi.spyOn(dataAuditApi, "boardStandard").mockResolvedValueOnce(review)
      .mockResolvedValueOnce({ ...review, review_version: "review-02", can_confirm: false });
    const confirm = vi.spyOn(dataAuditApi, "boardConfirm")
      .mockRejectedValue(new DataCenterApiError(409, "board_review_stale", "名单核查版本已变"));
    render(<DataAuditPage />);
    const dialog = within(await openBoard());
    fireEvent.click(await dialog.findByRole("button", { name: "确认并生成标准集" }));
    expect(await dialog.findByRole("alert")).toHaveTextContent("名单核查版本已变");
    expect(dialog.getByRole("button", { name: "确认并生成标准集" })).toBeDisabled();
    fireEvent.click(dialog.getByRole("button", { name: "重新读取" }));
    await waitFor(() => expect(dialog.getByRole("button", { name: "核查 Tushare" })).toBeEnabled());
    expect(dialog.getByRole("button", { name: "确认并生成标准集" })).toBeDisabled();
    expect(confirm).toHaveBeenCalledExactlyOnceWith(DAY, "review-01", expect.any(AbortSignal));
  });

  it("reads the saved standard after async confirm and refreshes only the selected day's summary", async () => {
    const standard = { business_date: DAY, version: "standard-today", boards: [candidate] };
    vi.spyOn(dataAuditApi, "boardStandard").mockResolvedValueOnce(review)
      .mockResolvedValueOnce({ ...review, state: "ready", standard, can_confirm: false });
    const submit = vi.spyOn(dataAuditApi, "boardConfirm").mockResolvedValue({ run_id: RUN, status: "QUEUED" });
    const run = vi.spyOn(dataAuditApi, "boardRun").mockResolvedValue({ run_id: RUN, status: "SUCCESS", result: standard });
    render(<DataAuditPage />);
    const dialog = within(await openBoard());
    fireEvent.click(await dialog.findByRole("button", { name: "确认并生成标准集" }));
    expect(dialog.getByRole("status")).toHaveTextContent("正在生成标准集");
    fireEvent.click(await dialog.findByRole("button", { name: "查看当日标准集" }, { timeout: 4000 }));
    expect(dialog.getByText("版本 standard-today")).toBeInTheDocument();
    expect(submit).toHaveBeenCalledExactlyOnceWith(DAY, "review-01", expect.any(AbortSignal));
    expect(run).toHaveBeenCalledExactlyOnceWith(RUN, expect.any(AbortSignal));
    await waitFor(() => expect(dataAuditApi.day).toHaveBeenCalledTimes(2));
    expect(vi.mocked(dataAuditApi.day).mock.calls.map(([day]) => day)).toEqual([DAY, DAY]);
  });
});
