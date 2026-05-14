import { Alert, Badge, Grid, Group, Loader, Stack, Table, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { OpsRealtimeStockRtDailyHealthResponse } from "../shared/api/realtime-types";
import { formatDateTimeLabel } from "../shared/date-format";
import { AlertBar } from "../shared/ui/alert-bar";
import { OpsTable, OpsTableCell, OpsTableCellText, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";

const HEALTH_API_PATH = "/api/v1/ops/realtime/stock-rt-daily/health";

const collectionStatusLabelMap: Record<string, string> = {
  open: "采集中",
  idle: "非采集时段",
  market_closed: "非交易日",
  disabled: "已停用",
};

function formatCollectionStatusLabel(value: string | null | undefined): string {
  return collectionStatusLabelMap[(value || "").toLowerCase()] || "未知";
}

function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 60) return `${value.toFixed(1)} 秒`;
  return `${Math.round(value / 60)} 分钟`;
}

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("zh-CN");
}

function formatDurationMs(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(0)} ms`;
}

function pollInterval(data: OpsRealtimeStockRtDailyHealthResponse | undefined): number | false {
  if (!data?.page_polling_enabled) return false;
  return Math.max(10, data.recommended_poll_interval_seconds || 60) * 1000;
}

export function OpsRealtimeMonitorPage() {
  const healthQuery = useQuery({
    queryKey: ["ops", "realtime", "stock-rt-daily", "health"],
    queryFn: () => apiRequest<OpsRealtimeStockRtDailyHealthResponse>(HEALTH_API_PATH),
    refetchInterval: (query) => pollInterval(query.state.data),
  });
  const health = healthQuery.data;

  return (
    <Stack gap="lg">
      <Text c="dimmed" size="sm">
        这里监控实时行情流本身：collector 是否应当采集、Redis 当前批次是否可读、以及最近一次上游请求和写入是否正常。
      </Text>

      {healthQuery.isLoading ? <Loader size="sm" /> : null}
      {healthQuery.error ? (
        <Alert color="error" title="读取实时流监控失败">
          {healthQuery.error instanceof Error ? healthQuery.error.message : "未知错误"}
        </Alert>
      ) : null}

      {health ? (
        <>
          <SectionCard
            title="股票实时日线"
            description="页面只读取实时流健康 API，不触发采集、不请求 Tushare、不读 Redis key。"
            action={
              <Group gap="xs">
                <StatusBadge value={health.status} />
                <Badge variant="light" color={health.page_polling_enabled ? "info" : "neutral"}>
                  {health.page_polling_enabled ? "页面局部刷新中" : "页面不轮询"}
                </Badge>
              </Group>
            }
          >
            <Grid>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard
                  label="采集状态"
                  value={formatCollectionStatusLabel(health.collection_status)}
                  hint={`采集窗口：${health.collection_sessions.join(" / ")}`}
                  hintDisplay="inline"
                />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard
                  label="当前批次"
                  value={health.current_batch_id || "—"}
                  hint={`批次年龄：${formatSeconds(health.current_batch_age_seconds)}`}
                  hintDisplay="inline"
                />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard
                  label="快照数量"
                  value={formatNumber(health.snapshot_count)}
                  hint={`源端返回：${formatNumber(health.source_row_count)} 行`}
                  hintDisplay="inline"
                />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard
                  label="限速"
                  value={`${health.request_count_last_minute}/${health.max_calls_per_minute}`}
                  hint="最近一分钟请求数 / feed 级上限"
                  hintDisplay="inline"
                />
              </Grid.Col>
            </Grid>
          </SectionCard>

          {health.status === "unavailable" ? (
            <AlertBar tone="error" title="实时流暂不可用">
              {health.last_error_message || "当前没有可读 Redis 批次，或 Redis 状态层不可连接。"}
            </AlertBar>
          ) : null}

          {health.status === "stale" ? (
            <AlertBar tone="warning" title="采集时段内刷新滞后">
              当前批次年龄为 {formatSeconds(health.current_batch_age_seconds)}，已超过 {health.stale_after_seconds} 秒阈值。
            </AlertBar>
          ) : null}

          <Grid>
            <Grid.Col span={{ base: 12, lg: 6 }}>
              <SectionCard title="采集与上游" description="collector 和 Tushare 请求侧状态。">
                <OpsTable>
                  <Table.Tbody>
                    <InfoRow label="Feed" value={`${health.display_name}（${health.feed_key}）`} />
                    <InfoRow label="Collector" value={health.collector_running ? "运行中" : "未观测到运行"} />
                    <InfoRow label="Collector ID" value={health.collector_id || "—"} />
                    <InfoRow label="最近请求" value={formatDateTimeLabel(health.last_request_at)} />
                    <InfoRow label="最近成功" value={formatDateTimeLabel(health.last_success_at)} />
                    <InfoRow label="源端耗时" value={formatDurationMs(health.source_elapsed_ms)} />
                    <InfoRow label="最近错误" value={health.last_error_message || "—"} />
                  </Table.Tbody>
                </OpsTable>
              </SectionCard>
            </Grid.Col>

            <Grid.Col span={{ base: 12, lg: 6 }}>
              <SectionCard title="Redis 当前批次" description="API 只读取 current pointer 指向的同一批次。">
                <OpsTable>
                  <Table.Tbody>
                    <InfoRow label="Redis 连接" value={health.redis_connected ? "可连接" : "不可连接"} />
                    <InfoRow label="批次接收时间" value={formatDateTimeLabel(health.current_batch_received_at)} />
                    <InfoRow label="批次发布时间" value={formatDateTimeLabel(health.current_batch_published_at)} />
                    <InfoRow label="Redis 写入耗时" value={formatDurationMs(health.write_elapsed_ms)} />
                    <InfoRow label="批次 TTL" value={`${formatNumber(health.snapshot_ttl_seconds)} 秒`} />
                    <InfoRow label="保留批次数" value={`${health.keep_recent_batches} 批`} />
                  </Table.Tbody>
                </OpsTable>
              </SectionCard>
            </Grid.Col>
          </Grid>

          <SectionCard title="Stream 事件" description="批次事件用于观测，逐股票变化事件为后续 WebSocket 预留。">
            <OpsTable>
              <Table.Thead>
                <Table.Tr>
                  <OpsTableHeaderCell align="left" width="28%">事件流</OpsTableHeaderCell>
                  <OpsTableHeaderCell align="left" width="36%">最近事件 ID</OpsTableHeaderCell>
                  <OpsTableHeaderCell align="left" width="36%">说明</OpsTableHeaderCell>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                <Table.Tr>
                  <OpsTableCell align="left" width="28%">
                    <OpsTableCellText fw={600}>batch_published</OpsTableCellText>
                  </OpsTableCell>
                  <OpsTableCell align="left" width="36%">
                    <OpsTableCellText ff="var(--mantine-font-family-monospace)" size="xs">
                      {health.last_batch_event_id || "—"}
                    </OpsTableCellText>
                  </OpsTableCell>
                  <OpsTableCell align="left" width="36%">
                    <OpsTableCellText size="sm">最近一次批次发布事件。</OpsTableCellText>
                  </OpsTableCell>
                </Table.Tr>
                <Table.Tr>
                  <OpsTableCell align="left" width="28%">
                    <OpsTableCellText fw={600}>quote_changed</OpsTableCellText>
                  </OpsTableCell>
                  <OpsTableCell align="left" width="36%">
                    <OpsTableCellText ff="var(--mantine-font-family-monospace)" size="xs">
                      {health.last_delta_event_id || "—"}
                    </OpsTableCellText>
                  </OpsTableCell>
                  <OpsTableCell align="left" width="36%">
                    <OpsTableCellText size="sm">
                      本批变化股票 {formatNumber(health.delta_count_last_batch)} 只。
                    </OpsTableCellText>
                  </OpsTableCell>
                </Table.Tr>
              </Table.Tbody>
            </OpsTable>
          </SectionCard>
        </>
      ) : null}
    </Stack>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <Table.Tr>
      <OpsTableCell align="left" width="34%">
        <OpsTableCellText c="dimmed" size="sm">{label}</OpsTableCellText>
      </OpsTableCell>
      <OpsTableCell align="left" width="66%">
        <OpsTableCellText size="sm">{value}</OpsTableCellText>
      </OpsTableCell>
    </Table.Tr>
  );
}
