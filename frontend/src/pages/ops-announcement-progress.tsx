import { Stack, Text } from "@mantine/core";
import type { AnnouncementProgress } from "../shared/api/announcement-types";
import { AlertBar } from "../shared/ui/alert-bar";

const phases: Record<AnnouncementProgress["phase"], string> = {
  planning: "规划", fetching: "读取", persisting: "保存", reconciling: "核对",
  completed: "日窗口完成", canceled: "已停止", failed: "失败",
};

export function OpsAnnouncementProgress({ progress }: { progress: AnnouncementProgress }) {
  const n = (value: number | undefined) => (value ?? 0).toLocaleString();
  const c = progress.counters;
  const q = progress.quality_counts;
  return (
    <AlertBar tone={progress.phase === "failed" ? "error" : progress.phase === "canceled" ? "warning" : "info"} title={`公告同步：${phases[progress.phase]}`}>
      <Stack gap={4}>
        <Text size="sm">{`当前 ${progress.ann_date ?? "—"}｜第 ${n(progress.page_number)} 页｜完成 ${n(progress.unit_done)}/${n(progress.unit_total)} 日`}</Text>
        <Text size="sm">{`读取 ${n(c.observed)}｜已提交输入 ${n(c.processed)}｜新增版本 ${n(c.inserted)}｜完全重复 ${n(c.identical)}｜残缺覆盖 ${n(c.covered)}｜拒绝 ${n(c.rejected)}`}</Text>
        <Text size="sm">{`删除冗余 ${n(c.deleted)}｜冲突组访问 ${n(c.conflicting_group_visits)}｜缺链接 ${n(q["quality.missing_url"])}｜缺时间 ${n(q["quality.missing_rec_time"])}`}</Text>
        <Text size="sm">{`真实请求累计 ${n(progress.issued_requests)}｜最近更新 ${progress.updated_at ?? "—"}｜预计完成：暂无法估算`}</Text>
      </Stack>
    </AlertBar>
  );
}
