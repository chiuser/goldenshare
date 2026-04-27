import { Badge, Box, Button, Grid, Group, Loader, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { DatasetCardListResponse, OpsOverviewResponse } from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { AlertBar } from "../shared/ui/alert-bar";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";

type CardStatus = "healthy" | "warning" | "failed" | "running" | "unknown";
type DatasetCard = DatasetCardListResponse["groups"][number]["items"][number];
type DatasetCardStage = DatasetCard["stage_statuses"][number];

function toCardStatus(rawStatus: string | null | undefined): CardStatus {
  const key = (rawStatus || "").toLowerCase();
  if (key === "running" || key === "queued" || key === "canceling") return "running";
  if (key === "failed" || key === "stale") return "failed";
  if (key === "warning" || key === "lagging") return "warning";
  if (key === "healthy" || key === "fresh" || key === "success") return "healthy";
  return "unknown";
}

function statusDotColor(status: CardStatus) {
  if (status === "running") return "var(--mantine-color-info-5)";
  if (status === "healthy") return "var(--mantine-color-success-5)";
  if (status === "failed") return "var(--mantine-color-error-5)";
  if (status === "warning") return "var(--mantine-color-warning-5)";
  return "var(--mantine-color-neutral-5)";
}

function configFlagPresentation(isOn: boolean) {
  return isOn
    ? { value: "active", label: "已配置" }
    : { value: "disabled", label: "未配置" };
}

function stageTimestamp(stage: DatasetCardStage): string {
  return stage.calculated_at ? formatDateTimeLabel(stage.calculated_at) : "—";
}

function cardSubtitle(item: DatasetCard): string {
  return `${item.domain_display_name} · ${item.delivery_mode_label}`;
}

function latestObservationLabel(item: DatasetCard): string {
  if (item.latest_observed_at) {
    return `最新时间：${formatDateTimeLabel(item.latest_observed_at)}`;
  }
  return `最新业务日期：${item.latest_business_date ? formatDateLabel(item.latest_business_date) : "—"}`;
}

export function OpsV21OverviewPage() {
  const summaryQuery = useQuery({
    queryKey: ["ops", "overview", "v21-overview-summary"],
    queryFn: () => apiRequest<OpsOverviewResponse>("/api/v1/ops/overview"),
  });
  const cardQuery = useQuery({
    queryKey: ["ops", "dataset-cards", "v21-overview"],
    queryFn: () => apiRequest<DatasetCardListResponse>("/api/v1/ops/dataset-cards"),
  });

  const isLoading = cardQuery.isLoading;
  const error = cardQuery.error;
  const groups = cardQuery.data?.groups || [];
  const cards = groups.flatMap((group) => group.items);

  return (
    <Stack gap="lg">
      <SectionCard
        title="状态概览"
        description="先看整体分布，再往下看各数据集当前链路状态。"
      >
        {summaryQuery.isLoading ? <Loader size="sm" /> : null}
        {summaryQuery.error ? (
          <AlertBar tone="error" title="读取状态概览失败">
            {summaryQuery.error instanceof Error ? summaryQuery.error.message : "未知错误"}
          </AlertBar>
        ) : null}
        {summaryQuery.data ? (
          <Grid>
            <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
              <StatCard label="数据集总数" value={summaryQuery.data.freshness_summary.total_datasets} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
              <StatCard label="状态正常" value={summaryQuery.data.freshness_summary.fresh_datasets} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
              <StatCard label="需要关注" value={summaryQuery.data.freshness_summary.lagging_datasets} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
              <StatCard
                label="严重滞后 / 未知"
                value={summaryQuery.data.freshness_summary.stale_datasets + summaryQuery.data.freshness_summary.unknown_datasets}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
              <StatCard label="已停用" value={summaryQuery.data.freshness_summary.disabled_datasets} />
            </Grid.Col>
          </Grid>
        ) : null}
      </SectionCard>

      {isLoading ? <Loader size="sm" /> : null}
      {error ? (
        <AlertBar tone="error" title="读取数据状态总览失败">
          {error instanceof Error ? error.message : "未知错误"}
        </AlertBar>
      ) : null}

      {!isLoading && !error && cards.length === 0 ? (
        <AlertBar tone="info" title="暂无可展示的数据集">
          当前还没有数据集卡片视图记录，请先执行一次状态重建。
        </AlertBar>
      ) : null}

      {groups.map((group) => (
        <SectionCard key={group.domain_key} title={group.domain_display_name} description={`共 ${group.items.length} 个数据集`}>
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md" verticalSpacing="md">
            {group.items.map((item) => {
              const status = toCardStatus(item.status);
              const flags: Array<{ label: string; on: boolean }> = [
                { label: "映射规则", on: item.std_mapping_configured },
                { label: "清洗规则", on: item.std_cleansing_configured },
                { label: "融合策略", on: item.resolution_policy_configured },
              ];

              return (
                <Paper
                  key={item.card_key}
                  data-testid={`overview-dataset-card-${item.card_key}`}
                  withBorder
                  radius="md"
                  p="lg"
                  style={{ minHeight: 278 }}
                >
                  <Stack gap={8} h="100%">
                    <Group justify="space-between" align="center" wrap="nowrap" gap={10}>
                      <Stack gap={2} justify="center" style={{ minWidth: 0, flex: 1 }}>
                        <Group gap={8} align="center" wrap="nowrap">
                          <Box
                            w={9}
                            h={9}
                            style={{ borderRadius: "50%", background: statusDotColor(status), flex: "0 0 auto" }}
                          />
                          <Text fw={600} size="lg" lineClamp={1} style={{ minWidth: 0 }}>
                            {item.display_name}
                          </Text>
                        </Group>
                        <Text size="xs" c="dimmed" ml={17} lineClamp={1}>
                          {cardSubtitle(item)}
                        </Text>
                      </Stack>
                      <Stack gap={4} align="flex-start" justify="center" style={{ flex: "0 0 auto", minWidth: 0 }}>
                        <Badge variant="light" color="info" size="sm">
                          {latestObservationLabel(item)}
                        </Badge>
                        <Badge variant="light" color="neutral" size="sm">
                          状态更新时间：{item.status_updated_at ? formatDateTimeLabel(item.status_updated_at) : "—"}
                        </Badge>
                      </Stack>
                      <Badge
                        variant="light"
                        color={item.delivery_mode_tone}
                        size="md"
                        style={{ flex: "0 0 auto", fontSize: 14 }}
                      >
                        {item.delivery_mode_label}
                      </Badge>
                    </Group>

                    <Stack gap={6}>
                      {item.stage_statuses.map((stage) => {
                        if (stage.stage === "raw" && item.raw_sources.length > 1) {
                          return (
                            <Stack key={stage.stage} gap={4}>
                              <Text size="sm" c="dimmed">
                                {stage.stage_label}
                              </Text>
                              {item.raw_sources.map((entry, sourceIndex) => (
                                <Group key={`${item.card_key}-raw-source-${sourceIndex}`} justify="space-between" align="center">
                                  <Text size="sm" c="dimmed">
                                    {entry.source_display_name}
                                    {entry.table_name ? `（${entry.table_name}）` : ""}
                                  </Text>
                                  <StatusBadge value={entry.status} />
                                </Group>
                              ))}
                            </Stack>
                          );
                        }
                        return (
                          <Group key={stage.stage} justify="space-between" align="center">
                            <Text size="sm" c="dimmed">
                              {stage.stage_label}
                              {stage.table_name ? `（${stage.table_name}）` : ""}
                            </Text>
                            <Group gap={8} wrap="nowrap">
                              <Text size="xs" c="dimmed">{stageTimestamp(stage)}</Text>
                              <StatusBadge value={stage.status} />
                            </Group>
                          </Group>
                        );
                      })}
                    </Stack>

                    <Grid gutter={6}>
                      {flags.map((flag) => (
                        <Grid.Col key={flag.label} span={4}>
                          <Paper withBorder radius="sm" p="xs">
                            <Stack gap={6}>
                              <Text size="xs" c="dimmed" fw={600}>{flag.label}</Text>
                              <StatusBadge
                                value={configFlagPresentation(flag.on).value}
                                label={configFlagPresentation(flag.on).label}
                                size="xs"
                              />
                            </Stack>
                          </Paper>
                        </Grid.Col>
                      ))}
                    </Grid>

                    <Group justify="space-between" mt="auto">
                      <Button
                        component="a"
                        href={`/app/ops/v21/datasets/detail/${encodeURIComponent(item.detail_dataset_key)}`}
                        size="xs"
                        variant="light"
                        color="brand"
                      >
                        查看详情
                      </Button>
                    </Group>
                  </Stack>
                </Paper>
              );
            })}
          </SimpleGrid>
        </SectionCard>
      ))}
    </Stack>
  );
}
