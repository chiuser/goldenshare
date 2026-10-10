import { Stack, Text } from "@mantine/core";
import type { WeeklyAdjProgress } from "../shared/api/weekly-adj-types";
import { formatDateTimeLabel } from "../shared/date-format";
import { AlertBar } from "../shared/ui/alert-bar";

export function OpsWeeklyAdjProgress({ progress }: { progress: WeeklyAdjProgress }) {
  return (
    <AlertBar tone="info" title={`复权周线：${progress.stage}`}>
      <Stack gap={4}>
        <Text size="sm">{`${progress.ts_code ?? "全市场"}｜${progress.trade_date ?? `${progress.start_date ?? "—"} 至 ${progress.end_date ?? "—"}`}｜第 ${progress.page_number} 页`}</Text>
        <Text size="sm">{`完成 ${progress.unit_done}/${progress.unit_total} 单元｜保留未刷新 ${progress.rows_preserved.toLocaleString()} 条`}</Text>
        <Text size="sm">{`最近更新 ${formatDateTimeLabel(progress.updated_at)}｜预计完成：暂无法估算`}</Text>
      </Stack>
    </AlertBar>
  );
}
