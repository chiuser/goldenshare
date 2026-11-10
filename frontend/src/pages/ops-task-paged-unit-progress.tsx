import { Stack, Text } from "@mantine/core";

import type {
  TaskRunPagedUnitActive,
  TaskRunPagedUnitProgress,
  TaskRunPagedUnitResult,
} from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import { AlertBar } from "../shared/ui/alert-bar";

function formatCount(value: number) {
  return value.toLocaleString();
}

function formatPeriod(point: string | null) {
  return point ? `截至 ${point}` : "当前处理单元";
}

function activeTone(phase: TaskRunPagedUnitActive["phase"]) {
  if (phase === "failed") {
    return "error" as const;
  }
  if (phase === "canceled") {
    return "warning" as const;
  }
  return "info" as const;
}

function activeTitle({ phase, time }: TaskRunPagedUnitActive) {
  const period = time.field === "trade_date" ? "当前周期" : "当前季度";
  if (phase === "failed") {
    return `${period}处理失败`;
  }
  if (phase === "canceled") {
    return `${period}已停止`;
  }
  return period;
}

function activeDescription(active: TaskRunPagedUnitActive) {
  const period = formatPeriod(active.time.point);
  const page = active.current_page_number ?? active.completed_page_count;
  const sourceComplete = `源端拉取完成：共 ${formatCount(active.completed_page_count)} 页、${formatCount(active.unit_rows_fetched)} 行`;

  if (active.phase === "processing_page") {
    return `${period}｜正在处理第 ${formatCount(page)} 页｜已完成 ${formatCount(active.completed_page_count)} 页｜累计读取 ${formatCount(active.unit_rows_fetched)} 行`;
  }
  if (active.phase === "reconciling") {
    return `${period}｜${sourceComplete}｜正在核对`;
  }
  if (active.phase === "publishing") {
    return `${period}｜${sourceComplete}｜正在正式写入`;
  }
  if (active.phase === "failed") {
    return `${period}｜处理停在第 ${formatCount(page)} 页｜已完成 ${formatCount(active.completed_page_count)} 页｜累计读取 ${formatCount(active.unit_rows_fetched)} 行`;
  }
  return `${period}｜停止时位于第 ${formatCount(page)} 页｜已完成 ${formatCount(active.completed_page_count)} 页｜累计读取 ${formatCount(active.unit_rows_fetched)} 行`;
}

function CompletedUnitResult({ result }: { result: TaskRunPagedUnitResult }) {
  return (
    <AlertBar tone="info" title={`${formatPeriod(result.time.point)}｜季度处理完成`}>
      <Stack gap={4}>
        <Text size="sm">
          {`源端：${formatCount(result.page_count)} 页，读取 ${formatCount(result.rows_fetched)} 行，完全重复去重 ${formatCount(result.rows_deduplicated)}，拒绝 ${formatCount(result.rows_rejected)}`}
        </Text>
        <Text size="sm">
          {`写入：保存 ${formatCount(result.rows_committed)}，首次插入 ${formatCount(result.rows_inserted_new)}，已存在且一致 ${formatCount(result.rows_matched_existing)}，最终范围 ${formatCount(result.final_scope_count)}`}
        </Text>
      </Stack>
    </AlertBar>
  );
}

export function OpsTaskPagedUnitProgress({ progress }: { progress: TaskRunPagedUnitProgress }) {
  const completed = [...progress.completed].sort((left, right) => right.unit_index - left.unit_index);

  return (
    <Stack gap="sm" style={{ fontVariantNumeric: "tabular-nums" }}>
      {progress.active ? (
        <AlertBar tone={activeTone(progress.active.phase)} title={activeTitle(progress.active)}>
          {progress.active.updated_at ? (
            <Stack gap={4}>
              <Text size="sm">{activeDescription(progress.active)}</Text>
              <Text size="xs" c="dimmed">最近更新 {formatDateTimeLabel(progress.active.updated_at)}</Text>
            </Stack>
          ) : activeDescription(progress.active)}
        </AlertBar>
      ) : null}
      {completed.map((result) => (
        <CompletedUnitResult key={`${result.unit_index}:${result.unit_id}`} result={result} />
      ))}
      {progress.completed_truncated ? (
        <AlertBar tone="warning" title="部分季度结果未展示">
          当前任务的完成结果已达到展示上限，任务级总计仍保留完整统计。
        </AlertBar>
      ) : null}
    </Stack>
  );
}
