import { Alert, Anchor, Grid, Loader, Stack, Table, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { OpsFreshnessResponse } from "../shared/api/types";
import { formatDateLabel } from "../shared/date-format";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";


const cadenceLabelMap: Record<string, string> = {
  reference: "基础更新",
  daily: "按日",
  weekly: "按周",
  monthly: "按月",
  event: "事件驱动",
};

export function OpsDataStatusPage() {
  const freshnessQuery = useQuery({
    queryKey: ["ops", "freshness"],
    queryFn: () => apiRequest<OpsFreshnessResponse>("/api/v1/ops/freshness"),
  });

  return (
    <Stack gap="lg">
      <PageHeader
        title="数据状态"
        description="这里直接回答“数据是不是最新”。如果有问题，优先提供下一步处理入口。"
      />

      {freshnessQuery.isLoading ? <Loader size="sm" /> : null}
      {freshnessQuery.error ? (
        <Alert color="red" title="无法读取数据状态">
          {freshnessQuery.error instanceof Error ? freshnessQuery.error.message : "未知错误"}
        </Alert>
      ) : null}

      {freshnessQuery.data ? (
        <>
          <Grid>
            <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
              <StatCard label="数据集总数" value={freshnessQuery.data.summary.total_datasets} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
              <StatCard label="状态正常" value={freshnessQuery.data.summary.fresh_datasets} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
              <StatCard label="需要关注" value={freshnessQuery.data.summary.lagging_datasets} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
              <StatCard label="严重滞后 / 未知" value={freshnessQuery.data.summary.stale_datasets + freshnessQuery.data.summary.unknown_datasets} />
            </Grid.Col>
          </Grid>

          {freshnessQuery.data.groups.map((group) => (
            <SectionCard
              key={group.domain_key}
              title={group.domain_display_name}
              description="先看最新日期和当前状态，再决定去任务记录还是直接手动同步。"
            >
              <Table highlightOnHover striped>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>数据名称</Table.Th>
                    <Table.Th>最新日期</Table.Th>
                    <Table.Th>更新频率</Table.Th>
                    <Table.Th>当前状态</Table.Th>
                    <Table.Th>最近异常</Table.Th>
                    <Table.Th>操作</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {group.items.map((item) => (
                    <Table.Tr key={item.dataset_key}>
                      <Table.Td>
                        <Stack gap={2}>
                          <Text fw={600}>{item.display_name}</Text>
                          {item.freshness_note ? (
                            <Text size="xs" c="dimmed">
                              {item.freshness_note}
                            </Text>
                          ) : null}
                        </Stack>
                      </Table.Td>
                      <Table.Td>{formatDateLabel(item.latest_business_date)}</Table.Td>
                      <Table.Td>{cadenceLabelMap[item.cadence] || "未定义"}</Table.Td>
                      <Table.Td>
                        <StatusBadge value={item.freshness_status} />
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" lineClamp={2}>
                          {item.recent_failure_summary || "当前没有异常摘要"}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Stack gap={4}>
                          {item.primary_execution_spec_key ? (
                            <Anchor
                              href={`/app/ops/tasks?spec_key=${encodeURIComponent(item.primary_execution_spec_key)}`}
                              size="sm"
                            >
                              查看任务
                            </Anchor>
                          ) : (
                            <Text c="dimmed" size="sm">—</Text>
                          )}
                          {item.primary_execution_spec_key ? (
                            <Anchor
                              component="a"
                              href={`/app/ops/manual-sync?spec_key=${encodeURIComponent(item.primary_execution_spec_key)}&spec_type=job`}
                              size="sm"
                            >
                              去处理
                            </Anchor>
                          ) : null}
                        </Stack>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </SectionCard>
          ))}
        </>
      ) : null}
    </Stack>
  );
}
