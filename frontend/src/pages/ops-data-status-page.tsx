import { Alert, Badge, Button, Grid, Group, Loader, Stack, Table, Text, Tooltip } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { OpsFreshnessResponse } from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { OpsTable, OpsTableActionGroup, OpsTableCell, OpsTableCellText, OpsTableHeaderCell } from "../shared/ui/ops-table";
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

function formatFailureLabel(summary: string | null) {
  return summary || "无";
}

function resolveAutoScheduleBadge(item: OpsFreshnessResponse["groups"][number]["items"][number]) {
  if (item.auto_schedule_status === "active") {
    return {
      label: "自动",
      color: "teal",
      tooltip: `已启用 ${item.auto_schedule_active}/${item.auto_schedule_total} 个自动任务${
        item.auto_schedule_next_run_at ? `，下次运行 ${formatDateTimeLabel(item.auto_schedule_next_run_at)}` : ""
      }。点击查看自动任务。`,
    };
  }
  if (item.auto_schedule_status === "paused") {
    return {
      label: "自动已暂停",
      color: "gray",
      tooltip: `已配置 ${item.auto_schedule_total} 个自动任务，当前都处于暂停状态。点击查看自动任务。`,
    };
  }
  return null;
}

export function OpsDataStatusPage() {
  const freshnessQuery = useQuery({
    queryKey: ["ops", "freshness"],
    queryFn: () => apiRequest<OpsFreshnessResponse>("/api/v1/ops/freshness"),
  });

  return (
    <Stack gap="lg">
      <Text c="dimmed" size="sm">
        有业务日期的数据会显示覆盖范围；没有业务日期的数据会显示最近一次同步日期。
      </Text>

      {freshnessQuery.isLoading ? <Loader size="sm" /> : null}
      {freshnessQuery.error ? (
        <Alert color="red" title="无法读取数据状态">
          {freshnessQuery.error instanceof Error ? freshnessQuery.error.message : "未知错误"}
        </Alert>
      ) : null}

      {freshnessQuery.data ? (
        <>
          <SectionCard
            title="状态概览"
            description="先看整体分布，再往下看各模块的数据覆盖范围和异常情况。"
          >
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
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard label="已停用" value={freshnessQuery.data.summary.disabled_datasets} />
              </Grid.Col>
            </Grid>
          </SectionCard>

          {freshnessQuery.data.groups.map((group) => (
            <SectionCard
              key={group.domain_key}
              title={group.domain_display_name}
              description="先看日期范围和当前状态，再决定是否立即处理。"
            >
              <OpsTable>
                <Table.Thead>
                  <Table.Tr>
                    <OpsTableHeaderCell align="left" width="22%">数据名称</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left" width="24%">日期范围</OpsTableHeaderCell>
                    <OpsTableHeaderCell width="12%">更新频率</OpsTableHeaderCell>
                    <OpsTableHeaderCell width="14%">当前状态</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left" width="18%">最近异常</OpsTableHeaderCell>
                    <OpsTableHeaderCell width="10%">操作</OpsTableHeaderCell>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {group.items.map((item) => {
                    const autoBadge = resolveAutoScheduleBadge(item);
                    return (
                      <Table.Tr key={item.dataset_key}>
                        <OpsTableCell align="left" width="22%">
                          <Group gap={6} wrap="wrap">
                            <OpsTableCellText fw={600} size="sm">{item.display_name}</OpsTableCellText>
                            {autoBadge ? (
                              <Tooltip label={autoBadge.tooltip}>
                                <Badge
                                  component="a"
                                  href={
                                    item.primary_execution_spec_key
                                      ? `/app/ops/automation?spec_key=${encodeURIComponent(item.primary_execution_spec_key)}&spec_type=job`
                                      : "/app/ops/automation"
                                  }
                                  size="sm"
                                  radius="sm"
                                  variant="light"
                                  color={autoBadge.color}
                                  style={{ cursor: "pointer" }}
                                >
                                  {autoBadge.label}
                                </Badge>
                              </Tooltip>
                            ) : null}
                          </Group>
                        </OpsTableCell>
                        <OpsTableCell align="left" width="24%">
                          <OpsTableCellText ff="IBM Plex Mono, SFMono-Regular, monospace" fw={500} size="xs">
                            {formatDateRangeLabel(item.earliest_business_date, item.latest_business_date, item.last_sync_date)}
                          </OpsTableCellText>
                        </OpsTableCell>
                        <OpsTableCell width="12%">
                          <OpsTableCellText size="xs">{cadenceLabelMap[item.cadence] || "未定义"}</OpsTableCellText>
                        </OpsTableCell>
                        <OpsTableCell width="14%">
                          <StatusBadge value={item.freshness_status} />
                        </OpsTableCell>
                        <OpsTableCell align="left" width="18%">
                          <OpsTableCellText lineClamp={1} size="xs" c={item.recent_failure_summary ? "var(--gs-magenta)" : "dimmed"}>
                            {formatFailureLabel(item.recent_failure_summary)}
                          </OpsTableCellText>
                        </OpsTableCell>
                        <OpsTableCell width="10%">
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
                            ) : <OpsTableCellText c="dimmed">—</OpsTableCellText>}
                          </OpsTableActionGroup>
                        </OpsTableCell>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </OpsTable>
            </SectionCard>
          ))}
        </>
      ) : null}
    </Stack>
  );
}
