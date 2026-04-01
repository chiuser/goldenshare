import { Alert, Button, Grid, Loader, Stack, Table } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { OpsFreshnessResponse } from "../shared/api/types";
import { formatDateLabel } from "../shared/date-format";
import { OpsTable, OpsTableActionGroup, OpsTableCell, OpsTableCellText, OpsTableHeaderCell } from "../shared/ui/ops-table";
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

export function OpsDataStatusPage() {
  const freshnessQuery = useQuery({
    queryKey: ["ops", "freshness"],
    queryFn: () => apiRequest<OpsFreshnessResponse>("/api/v1/ops/freshness"),
  });

  return (
    <Stack gap="lg">
      <PageHeader
        title="数据状态"
        description="这里直接回答“数据是不是最新”。有业务日期的数据会显示覆盖范围；没有业务日期的数据会显示最近一次同步日期。"
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
              <OpsTable>
                <Table.Thead>
                  <Table.Tr>
                    <OpsTableHeaderCell>数据名称</OpsTableHeaderCell>
                    <OpsTableHeaderCell>日期范围</OpsTableHeaderCell>
                    <OpsTableHeaderCell>更新频率</OpsTableHeaderCell>
                    <OpsTableHeaderCell>当前状态</OpsTableHeaderCell>
                    <OpsTableHeaderCell>最近异常</OpsTableHeaderCell>
                    <OpsTableHeaderCell>操作</OpsTableHeaderCell>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {group.items.map((item) => (
                    <Table.Tr key={item.dataset_key}>
                      <OpsTableCell>
                        <OpsTableCellText fw={600}>{item.display_name}</OpsTableCellText>
                      </OpsTableCell>
                      <OpsTableCell>
                        <OpsTableCellText>{formatDateRangeLabel(item.earliest_business_date, item.latest_business_date, item.last_sync_date)}</OpsTableCellText>
                      </OpsTableCell>
                      <OpsTableCell>
                        <OpsTableCellText>{cadenceLabelMap[item.cadence] || "未定义"}</OpsTableCellText>
                      </OpsTableCell>
                      <OpsTableCell>
                        <StatusBadge value={item.freshness_status} />
                      </OpsTableCell>
                      <OpsTableCell>
                        <OpsTableCellText lineClamp={2}>
                          {item.recent_failure_summary || "当前没有异常摘要"}
                        </OpsTableCellText>
                      </OpsTableCell>
                      <OpsTableCell>
                        <OpsTableActionGroup>
                          {item.primary_execution_spec_key ? (
                            <Button
                              component="a"
                              href={`/app/ops/manual-sync?spec_key=${encodeURIComponent(item.primary_execution_spec_key)}&spec_type=job`}
                              size="xs"
                              variant="default"
                            >
                              去处理
                            </Button>
                          ) : <OpsTableCellText c="dimmed">—</OpsTableCellText>}
                        </OpsTableActionGroup>
                      </OpsTableCell>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </OpsTable>
            </SectionCard>
          ))}
        </>
      ) : null}
    </Stack>
  );
}
