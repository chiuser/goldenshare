import { Alert, Button, Grid, Loader, Stack, Table, Text } from "@mantine/core";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { OpsOverviewResponse } from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { formatSpecDisplayLabel, formatTriggerSourceLabel } from "../shared/ops-display";
import { OpsTable, OpsTableActionGroup, OpsTableCell, OpsTableCellText, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";

function formatDateRangeLabel(earliestDate: string | null, latestDate: string | null, lastSyncDate: string | null) {
  if (earliestDate && latestDate) {
    if (earliestDate === latestDate) {
      return formatDateLabel(latestDate);
    }
    return `${formatDateLabel(earliestDate)} ~ ${formatDateLabel(latestDate)}`;
  }
  if (lastSyncDate) {
    return formatDateLabel(lastSyncDate);
  }
  return formatDateLabel(latestDate);
}

export function OpsTodayPage() {
  const overviewQuery = useQuery({
    queryKey: ["ops", "overview"],
    queryFn: () => apiRequest<OpsOverviewResponse>("/api/v1/ops/overview"),
  });

  const overview = overviewQuery.data;

  return (
    <Stack gap="lg">
      <Text c="dimmed" size="sm">
        先看今天整体运行是否正常，再决定要不要处理失败任务或补同步。
      </Text>

      {overviewQuery.isLoading ? <Loader size="sm" /> : null}
      {overviewQuery.error ? (
        <Alert color="error" title="无法读取今日运行">
          {overviewQuery.error instanceof Error ? overviewQuery.error.message : "未知错误"}
        </Alert>
      ) : null}

      {overview ? (
        <>
          <SectionCard
            title="今日概览"
            description="先看今天的任务分布，再往下决定是看任务，还是直接处理数据。"
          >
            <Grid>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard
                  label="今日任务总数"
                  value={overview.today_kpis.total_requests}
                  hint={`统计 ${overview.today_kpis.business_date} 这一天发起的任务请求。`}
                />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard label="已完成" value={overview.today_kpis.completed_requests} hint="今天已经结束的任务数量。" />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard label="正在处理" value={overview.today_kpis.running_requests} hint="当前仍在执行中的任务数量。" />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard label="执行失败" value={overview.today_kpis.failed_requests} hint="今天失败的任务数量。" />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard label="等待处理" value={overview.today_kpis.queued_requests} hint="已经发起但还没开始处理的任务数量。" />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard label="需要关注" value={overview.today_kpis.attention_dataset_count} hint="当前状态不是“正常”的数据集数量。" />
              </Grid.Col>
            </Grid>
          </SectionCard>

          <SectionCard
            title="最近任务记录"
            description="展示最近发起或完成的任务，方便快速进入任务详情页继续处理。"
            action={
              <Button component={Link} to="/ops/tasks" size="xs" variant="light">
                查看全部任务
              </Button>
            }
          >
            <OpsTable>
              <Table.Thead>
                <Table.Tr>
                  <OpsTableHeaderCell align="left" width="36%">任务名称</OpsTableHeaderCell>
                  <OpsTableHeaderCell width="14%">发起方式</OpsTableHeaderCell>
                  <OpsTableHeaderCell align="left" width="24%">开始时间</OpsTableHeaderCell>
                  <OpsTableHeaderCell width="14%">当前状态</OpsTableHeaderCell>
                  <OpsTableHeaderCell width="12%">操作</OpsTableHeaderCell>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {overview.recent_executions.slice(0, 8).map((item) => (
                  <Table.Tr key={item.id}>
                    <OpsTableCell align="left" width="36%">
                      <OpsTableCellText fw={600} size="sm">{formatSpecDisplayLabel(item.spec_key, item.spec_display_name)}</OpsTableCellText>
                    </OpsTableCell>
                    <OpsTableCell width="14%">
                      <OpsTableCellText size="xs">{formatTriggerSourceLabel(item.trigger_source)}</OpsTableCellText>
                    </OpsTableCell>
                    <OpsTableCell align="left" width="24%">
                      <OpsTableCellText ff="var(--mantine-font-family-monospace)" fw={500} size="xs">
                        {formatDateTimeLabel(item.requested_at)}
                      </OpsTableCellText>
                    </OpsTableCell>
                    <OpsTableCell width="14%">
                      <StatusBadge value={item.status} />
                    </OpsTableCell>
                    <OpsTableCell width="12%">
                      <OpsTableActionGroup>
                        <Button component="a" href={`/app/ops/tasks/${item.id}`} size="xs" variant="light" color="brand">
                          查看详情
                        </Button>
                      </OpsTableActionGroup>
                    </OpsTableCell>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </OpsTable>
          </SectionCard>

          <SectionCard
            title="需要关注的数据"
            description="这里显示当前不是“正常”状态的数据，方便快速判断要不要补同步。"
          >
            <OpsTable>
              <Table.Thead>
                <Table.Tr>
                  <OpsTableHeaderCell align="left" width="26%">数据名称</OpsTableHeaderCell>
                  <OpsTableHeaderCell align="left" width="20%">日期范围 / 最近同步日期</OpsTableHeaderCell>
                  <OpsTableHeaderCell width="12%">当前状态</OpsTableHeaderCell>
                  <OpsTableHeaderCell align="left" width="30%">最近异常</OpsTableHeaderCell>
                  <OpsTableHeaderCell width="12%">操作</OpsTableHeaderCell>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {overview.lagging_datasets.map((item) => (
                  <Table.Tr key={item.dataset_key}>
                    <OpsTableCell align="left" width="26%">
                      <OpsTableCellText fw={600} size="sm">{item.display_name}</OpsTableCellText>
                    </OpsTableCell>
                    <OpsTableCell align="left" width="20%">
                      <OpsTableCellText ff="var(--mantine-font-family-monospace)" fw={500} size="xs">
                        {formatDateRangeLabel(
                          item.earliest_business_date ?? null,
                          item.latest_business_date ?? null,
                          item.last_sync_date ?? null,
                        )}
                      </OpsTableCellText>
                    </OpsTableCell>
                    <OpsTableCell width="12%">
                      <StatusBadge value={item.freshness_status} />
                    </OpsTableCell>
                    <OpsTableCell align="left" width="30%">
                      {(item.recent_failure_summary || item.recent_failure_message) ? (
                        <Stack gap={2}>
                          <OpsTableCellText c="error" size="xs">
                            {item.recent_failure_summary || item.recent_failure_message}
                          </OpsTableCellText>
                          {item.recent_failure_at ? (
                            <OpsTableCellText c="dimmed" ff="var(--mantine-font-family-monospace)" size="xs">
                              {formatDateTimeLabel(item.recent_failure_at)}
                            </OpsTableCellText>
                          ) : null}
                        </Stack>
                      ) : (
                        <OpsTableCellText c="dimmed" size="xs">—</OpsTableCellText>
                      )}
                    </OpsTableCell>
                    <OpsTableCell width="12%">
                      <OpsTableActionGroup>
                        {item.primary_execution_spec_key ? (
                          <Button
                            component="a"
                            href={`/app/ops/manual-sync?spec_key=${encodeURIComponent(item.primary_execution_spec_key)}&spec_type=job`}
                            size="xs"
                            variant="light"
                            color="brand"
                          >
                            去处理
                          </Button>
                        ) : (
                          <Button component={Link} to="/ops/tasks" size="xs" variant="light" color="brand">
                            去处理
                          </Button>
                        )}
                      </OpsTableActionGroup>
                    </OpsTableCell>
                  </Table.Tr>
                ))}
                {!overview.lagging_datasets.length ? (
                  <Table.Tr>
                    <Table.Td colSpan={5}>
                      <Text c="dimmed" size="sm">
                        当前没有需要关注的数据。
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ) : null}
              </Table.Tbody>
            </OpsTable>
          </SectionCard>
        </>
      ) : null}
    </Stack>
  );
}
