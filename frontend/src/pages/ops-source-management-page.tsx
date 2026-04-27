import { Alert, Badge, Grid, Group, Loader, Stack, Table, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type {
  SourceManagementBridgeResponse,
} from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import { EmptyState } from "../shared/ui/empty-state";
import { OpsTable, OpsTableCell, OpsTableCellText, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";

function datasetLabel(item: { dataset_display_name?: string | null }) {
  return item.dataset_display_name || "数据集名称缺失";
}

function sourceLabel(item: { source_display_name?: string | null }) {
  return item.source_display_name || "来源名称缺失";
}

function stageLabel(item: { stage_display_name?: string | null }) {
  return item.stage_display_name || "层级名称缺失";
}

export function OpsSourceManagementPage() {
  const bridgeQuery = useQuery({
    queryKey: ["ops", "source-management-bridge"],
    queryFn: () => apiRequest<SourceManagementBridgeResponse>("/api/v1/ops/source-management/bridge"),
  });
  const loading = bridgeQuery.isLoading;
  const error = bridgeQuery.error;

  const summary = bridgeQuery.data?.summary;
  const probeItems = bridgeQuery.data?.probe_rules ?? [];
  const releaseItems = bridgeQuery.data?.releases ?? [];
  const mappingItems = bridgeQuery.data?.std_mapping_rules ?? [];
  const cleansingItems = bridgeQuery.data?.std_cleansing_rules ?? [];
  const latestItems = bridgeQuery.data?.layer_latest ?? [];

  const stageList = ["raw", "std", "resolution", "serving"];
  return (
    <Stack gap="lg">
      <PageHeader
        title="数据源管理"
        description="这里继续使用桥接看板方式承接新版多源对象，只做查询可视化，不在本批扩出写操作工作区。"
      />

      <SectionCard
        title="桥接看板摘要"
        description="在不改动旧页面流程的前提下，先承接多源模型中的探测、发布、规则与分层快照。"
      >
        {loading ? <Loader size="sm" /> : null}
        {error ? (
          <Alert color="error" title="读取新版能力数据失败">
            {error instanceof Error ? error.message : "未知错误"}
          </Alert>
        ) : null}

        {!loading && !error ? (
          <>
            <Grid mb="md">
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard label="探测规则（启用）" value={`${summary?.probe_active ?? 0}/${summary?.probe_total ?? 0}`} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard label="发布任务（运行中）" value={summary?.release_running ?? 0} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard label="标准化规则（启用）" value={`${(summary?.std_mapping_active ?? 0) + (summary?.std_cleansing_active ?? 0)}`} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard label="分层快照失败项" value={summary?.layer_latest_failed ?? 0} />
              </Grid.Col>
            </Grid>

            <Text c="dimmed" size="sm">
              当前是桥接阶段，只做查询可视化，不做复杂写操作入口。后续 UI 重构时会把探测、发布、规则编辑拆分成独立工作区。
            </Text>
          </>
        ) : null}
      </SectionCard>

      <SectionCard title="分层快照（Latest）" description="按 dataset/source/stage 去重后的最新状态，用来快速判断多源链路卡在哪一层。">
        <OpsTable>
          <Table.Thead>
            <Table.Tr>
              <OpsTableHeaderCell align="left" width="24%">数据集 / 来源</OpsTableHeaderCell>
              <OpsTableHeaderCell width="14%">层级</OpsTableHeaderCell>
              <OpsTableHeaderCell width="14%">状态</OpsTableHeaderCell>
              <OpsTableHeaderCell width="14%">记录数</OpsTableHeaderCell>
              <OpsTableHeaderCell align="left" width="16%">快照日期</OpsTableHeaderCell>
              <OpsTableHeaderCell align="left" width="18%">最近计算</OpsTableHeaderCell>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {latestItems.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <EmptyState title="暂无分层快照" description="当前还没有可展示的最新层级状态。" />
                </Table.Td>
              </Table.Tr>
            ) : latestItems.slice(0, 30).map((item, index) => (
              <Table.Tr key={`${item.dataset_key}-${item.source_key ?? "none"}-${item.stage}-${index}`}>
                <OpsTableCell align="left" width="24%">
                  <Stack gap={2}>
                    <OpsTableCellText fw={600} size="sm">{datasetLabel(item)}</OpsTableCellText>
                    <OpsTableCellText size="xs" c="dimmed">{sourceLabel(item)}</OpsTableCellText>
                  </Stack>
                </OpsTableCell>
                <OpsTableCell width="14%">
                  <Badge size="sm" variant="light" color={stageList.includes(item.stage) ? "brand" : "gray"}>
                    {stageLabel(item)}
                  </Badge>
                </OpsTableCell>
                <OpsTableCell width="14%">
                  <StatusBadge value={item.status} />
                </OpsTableCell>
                <OpsTableCell width="14%">
                  <OpsTableCellText size="xs">{item.rows_out ?? item.rows_in ?? 0}</OpsTableCellText>
                </OpsTableCell>
                <OpsTableCell align="left" width="16%">
                  <OpsTableCellText size="xs">{item.snapshot_date}</OpsTableCellText>
                </OpsTableCell>
                <OpsTableCell align="left" width="18%">
                  <OpsTableCellText size="xs">{formatDateTimeLabel(item.calculated_at)}</OpsTableCellText>
                </OpsTableCell>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </OpsTable>
      </SectionCard>

      <Grid>
        <Grid.Col span={{ base: 12, xl: 6 }}>
          <SectionCard title="探测规则（Probe）" description="用于自动探测源数据是否就绪并触发任务。">
            <Stack gap="xs">
              {probeItems.slice(0, 8).map((item) => (
                <Group key={item.id} justify="space-between" wrap="nowrap">
                  <Stack gap={0}>
                    <Text size="sm" fw={600}>{item.name}</Text>
                    <Text size="xs" c="dimmed">{datasetLabel(item)} · {sourceLabel(item)}</Text>
                  </Stack>
                  <Group gap={8}>
                    <StatusBadge value={item.status} />
                    <Text size="xs" c="dimmed">{item.probe_interval_seconds}s</Text>
                  </Group>
                </Group>
              ))}
              {probeItems.length === 0 ? <EmptyState title="暂无探测规则" description="当前还没有可展示的自动探测规则。" /> : null}
            </Stack>
          </SectionCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, xl: 6 }}>
          <SectionCard title="发布流水（Resolution Release）" description="记录策略发布与回滚过程的执行状态。">
            <Stack gap="xs">
              {releaseItems.slice(0, 8).map((item) => (
                <Group key={item.id} justify="space-between" wrap="nowrap">
                  <Stack gap={0}>
                    <Text size="sm" fw={600}>{datasetLabel(item)} · v{item.target_policy_version}</Text>
                    <Text size="xs" c="dimmed">{formatDateTimeLabel(item.triggered_at)}</Text>
                  </Stack>
                  <StatusBadge value={item.status} />
                </Group>
              ))}
              {releaseItems.length === 0 ? <EmptyState title="暂无发布记录" description="当前还没有可展示的策略发布或回滚记录。" /> : null}
            </Stack>
          </SectionCard>
        </Grid.Col>
      </Grid>

      <Grid>
        <Grid.Col span={{ base: 12, xl: 6 }}>
          <SectionCard title="标准化映射规则（Mapping）" description="字段级映射规则，支撑 raw → std。">
            <Stack gap="xs">
              {mappingItems.slice(0, 8).map((item) => (
                <Group key={item.id} justify="space-between" wrap="nowrap">
                  <Stack gap={0}>
                    <Text size="sm" fw={600}>{datasetLabel(item)} · {sourceLabel(item)}</Text>
                    <Text size="xs" c="dimmed">{item.src_field} → {item.std_field}</Text>
                  </Stack>
                  <Group gap={8}>
                    <Badge size="sm" variant="light" color="gray">v{item.rule_set_version}</Badge>
                    <StatusBadge value={item.status} />
                  </Group>
                </Group>
              ))}
              {mappingItems.length === 0 ? <EmptyState title="暂无映射规则" description="当前还没有可展示的字段映射规则。" /> : null}
            </Stack>
          </SectionCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, xl: 6 }}>
          <SectionCard title="标准化清洗规则（Cleansing）" description="数据质量清洗规则，支撑 std 入层前处理。">
            <Stack gap="xs">
              {cleansingItems.slice(0, 8).map((item) => (
                <Group key={item.id} justify="space-between" wrap="nowrap">
                  <Stack gap={0}>
                    <Text size="sm" fw={600}>{datasetLabel(item)} · {sourceLabel(item)}</Text>
                    <Text size="xs" c="dimmed">{item.rule_type} / {item.action}</Text>
                  </Stack>
                  <Group gap={8}>
                    <Badge size="sm" variant="light" color="gray">v{item.rule_set_version}</Badge>
                    <StatusBadge value={item.status} />
                  </Group>
                </Group>
              ))}
              {cleansingItems.length === 0 ? <EmptyState title="暂无清洗规则" description="当前还没有可展示的数据质量清洗规则。" /> : null}
            </Stack>
          </SectionCard>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
