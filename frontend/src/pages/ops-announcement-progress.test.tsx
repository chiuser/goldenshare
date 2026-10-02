import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { appTheme } from "../app/theme";
import { OpsAnnouncementProgress } from "./ops-announcement-progress";

it("分别显示提交输入、物理合并及缺字段质量，ETA 不估算", () => {
  render(<MantineProvider theme={appTheme}><OpsAnnouncementProgress progress={{
    phase: "persisting", ann_date: "2026-01-01", page_number: 2, offset: 2000,
    unit_done: 1, unit_total: 3, issued_requests: 4, updated_at: "2026-10-02T00:00:00Z",
    counters: { observed: 2001, processed: 500, inserted: 400, identical: 50, covered: 50, rejected: 0, deleted: 20 },
    quality_counts: { "quality.missing_url": 2, "quality.missing_rec_time": 3 },
  }} /></MantineProvider>);
  expect(screen.getByText(/完成 1\/3 日/)).toBeInTheDocument();
  expect(screen.getByText(/已提交输入 500/)).toHaveTextContent("拒绝 0");
  expect(screen.getByText(/删除冗余 20/)).toHaveTextContent("缺链接 2｜缺时间 3");
  expect(screen.getByText(/真实请求累计 4/)).toHaveTextContent("预计完成：暂无法估算");
});
