import { Alert, Button, Grid, Loader, Stack, Table, Text } from "@mantine/core";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { OpsOverviewResponse } from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { formatSpecDisplayLabel, formatTriggerSourceLabel } from "../shared/ops-display";
import { OpsTable, OpsTableActionGroup, OpsTableCell, OpsTableCellText, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";


export function OpsTodayPage() {
  const overviewQuery = useQuery({
    queryKey: ["ops", "overview"],
    queryFn: () => apiRequest<OpsOverviewResponse>("/api/v1/ops/overview"),
  });

  const overview = overviewQuery.data;

  return (
    <Stack gap="lg">
      <PageHeader
        title="今日运行"
        description="先看今天系统整体是否正常，再决定要不要处理失败任务或补同步。"
      />

      {overviewQuery.isLoading ? <Loader size="sm" /> : null}
      {overviewQuery.error ? (
        <Alert color="red" title="无法读取今日运行">
          {overviewQuery.error instanceof Error ? overviewQuery.error.message : "未知错误"}
        </Alert>
      ) : null}

      {overview ? (
        <>
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
                  <OpsTableHeaderCell>任务名称</OpsTableHeaderCell>
                  <OpsTableHeaderCell>发起方式</OpsTableHeaderCell>
                  <OpsTableHeaderCell>开始时间</OpsTableHeaderCell>
                  <OpsTableHeaderCell>当前状态</OpsTableHeaderCell>
                  <OpsTableHeaderCell>操作</OpsTableHeaderCell>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {overview.recent_executions.slice(0, 8).map((item) => (
                  <Table.Tr key={item.id}>
                    <OpsTableCell>
                      <OpsTableCellText fw={600}>{formatSpecDisplayLabel(item.spec_key, item.spec_display_name)}</OpsTableCellText>
                    </OpsTableCell>
                    <OpsTableCell>
                      <OpsTableCellText>{formatTriggerSourceLabel(item.trigger_source)}</OpsTableCellText>
                    </OpsTableCell>
                    <OpsTableCell>
                      <OpsTableCellText>{formatDateTimeLabel(item.requested_at)}</OpsTableCellText>
                    </OpsTableCell>
                    <OpsTableCell>
                      <StatusBadge value={item.status} />
                    </OpsTableCell>
                    <OpsTableCell>
                      <OpsTableActionGroup>
                        <Button component="a" href={`/app/ops/tasks/${item.id}`} size="xs" variant="light">
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
            action={
              <Button component={Link} to="/ops/data-status" size="xs" variant="light">
                查看全部数据
              </Button>
            }
          >
            <OpsTable>
              <Table.Thead>
                <Table.Tr>
                  <OpsTableHeaderCell>数据名称</OpsTableHeaderCell>
                  <OpsTableHeaderCell>最新日期</OpsTableHeaderCell>
                  <OpsTableHeaderCell>当前状态</OpsTableHeaderCell>
                  <OpsTableHeaderCell>操作</OpsTableHeaderCell>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {overview.lagging_datasets.slice(0, 5).map((item) => (
                  <Table.Tr key={item.dataset_key}>
                    <OpsTableCell>
                      <OpsTableCellText fw={600}>{item.display_name}</OpsTableCellText>
                    </OpsTableCell>
                    <OpsTableCell>
                      <OpsTableCellText>{formatDateLabel(item.latest_business_date)}</OpsTableCellText>
                    </OpsTableCell>
                    <OpsTableCell>
                      <StatusBadge value={item.freshness_status} />
                    </OpsTableCell>
                    <OpsTableCell>
                      <OpsTableActionGroup>
                        {item.primary_execution_spec_key ? (
                          <Button
                            component="a"
                            href={`/app/ops/manual-sync?spec_key=${encodeURIComponent(item.primary_execution_spec_key)}&spec_type=job`}
                            size="xs"
                            variant="light"
                          >
                            去处理
                          </Button>
                        ) : (
                          <Button component={Link} to="/ops/tasks" size="xs" variant="light">
                            去处理
                          </Button>
                        )}
                      </OpsTableActionGroup>
                    </OpsTableCell>
                  </Table.Tr>
                ))}
                {!overview.lagging_datasets.length ? (
                  <Table.Tr>
                    <Table.Td colSpan={4}>
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
