import { Alert, Anchor, Grid, Group, Loader, Stack, Table, Text } from "@mantine/core";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { OpsOverviewResponse } from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { formatSpecDisplayLabel, formatTriggerSourceLabel } from "../shared/ops-display";
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

  const priorityItems = (() => {
    if (!overview) return [];
    const items: Array<{
      key: string;
      title: string;
      description: string;
      href: string;
      actionLabel: string;
    }> = [];

    for (const item of overview.recent_failures.slice(0, 2)) {
      items.push({
        key: `failed-${item.id}`,
        title: formatSpecDisplayLabel(item.spec_key, item.spec_display_name),
        description: `最近一次执行失败，发起方式：${formatTriggerSourceLabel(item.trigger_source)}。`,
        href: `/app/ops/tasks/${item.id}`,
        actionLabel: "查看详情",
      });
    }

    for (const item of overview.lagging_datasets.slice(0, 2)) {
      items.push({
        key: `dataset-${item.dataset_key}`,
        title: item.display_name,
        description: `最新业务日 ${formatDateLabel(item.latest_business_date)}，建议尽快检查。`,
        href: `/app/ops/data-status`,
        actionLabel: "去处理",
      });
    }

    return items.slice(0, 4);
  })();

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

          <Grid align="stretch">
            <Grid.Col span={{ base: 12, xl: 5 }}>
              <SectionCard
                title="需要优先处理的问题"
                description="优先展示最近失败的任务和当前滞后的数据，方便第一时间处理。"
              >
                {priorityItems.length ? (
                  <Stack gap="sm">
                    {priorityItems.map((item) => (
                      <Group key={item.key} justify="space-between" align="flex-start" gap="md">
                        <Stack gap={2}>
                          <Text fw={600}>{item.title}</Text>
                          <Text c="dimmed" size="sm">
                            {item.description}
                          </Text>
                        </Stack>
                        <Anchor component="a" href={item.href} size="sm">
                          {item.actionLabel}
                        </Anchor>
                      </Group>
                    ))}
                  </Stack>
                ) : (
                  <Alert color="teal" variant="light" title="今天暂时没有需要优先处理的问题">
                    当前没有发现新的失败任务，也没有明显滞后的关键数据。
                  </Alert>
                )}
              </SectionCard>
            </Grid.Col>

            <Grid.Col span={{ base: 12, xl: 7 }}>
              <SectionCard
                title="需要关注的数据"
                description="这里显示当前不是“正常”状态的数据，方便快速判断要不要补同步。"
                action={
                  <Anchor component={Link} to="/ops/data-status" size="sm">
                    查看全部
                  </Anchor>
                }
              >
                <Table highlightOnHover striped>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>数据名称</Table.Th>
                      <Table.Th>最新日期</Table.Th>
                      <Table.Th>当前状态</Table.Th>
                      <Table.Th>操作</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {overview.lagging_datasets.slice(0, 5).map((item) => (
                      <Table.Tr key={item.dataset_key}>
                        <Table.Td>{item.display_name}</Table.Td>
                        <Table.Td>{formatDateLabel(item.latest_business_date)}</Table.Td>
                        <Table.Td>
                          <StatusBadge value={item.freshness_status} />
                        </Table.Td>
                        <Table.Td>
                          <Anchor component={Link} to="/ops/data-status" size="sm">
                            去处理
                          </Anchor>
                        </Table.Td>
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
                </Table>
              </SectionCard>
            </Grid.Col>
          </Grid>

          <SectionCard
            title="最近任务记录"
            description="展示最近发起或完成的任务，方便快速进入任务详情页继续处理。"
            action={
              <Group gap="md">
                <Anchor component={Link} to="/ops/manual-sync" size="sm">
                  去手动同步
                </Anchor>
                <Anchor component={Link} to="/ops/tasks" size="sm">
                  查看全部任务
                </Anchor>
              </Group>
            }
          >
            <Table highlightOnHover striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>任务名称</Table.Th>
                  <Table.Th>发起方式</Table.Th>
                  <Table.Th>开始时间</Table.Th>
                  <Table.Th>当前状态</Table.Th>
                  <Table.Th>操作</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {overview.recent_executions.slice(0, 8).map((item) => (
                  <Table.Tr key={item.id}>
                    <Table.Td>{formatSpecDisplayLabel(item.spec_key, item.spec_display_name)}</Table.Td>
                    <Table.Td>{formatTriggerSourceLabel(item.trigger_source)}</Table.Td>
                    <Table.Td>{formatDateTimeLabel(item.requested_at)}</Table.Td>
                    <Table.Td>
                      <StatusBadge value={item.status} />
                    </Table.Td>
                    <Table.Td>
                      <Anchor component="a" href={`/app/ops/tasks/${item.id}`} size="sm">
                        查看详情
                      </Anchor>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </SectionCard>
        </>
      ) : null}
    </Stack>
  );
}
