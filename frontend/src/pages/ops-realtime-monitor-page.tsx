import { Alert, Badge, Grid, Group, Loader, Stack, Table, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type {
  OpsRealtimeEtfRtDailyHealthResponse,
  OpsRealtimeStockRtDailyHealthResponse,
  OpsRealtimeStockRtMinHealthItem,
  OpsRealtimeStockRtMinHealthResponse,
} from "../shared/api/realtime-types";
import { formatDateTimeLabel } from "../shared/date-format";
import { AlertBar } from "../shared/ui/alert-bar";
import { OpsTable, OpsTableCell, OpsTableCellText, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";

const DAILY_HEALTH_API_PATH = "/api/v1/ops/realtime/stock-rt-daily/health";
const MINUTE_HEALTH_API_PATH = "/api/v1/ops/realtime/stock-rt-min/health";
const ETF_HEALTH_API_PATH = "/api/v1/ops/realtime/etf-rt-daily/health";

interface PollingPayload {
  page_polling_enabled: boolean;
  recommended_poll_interval_seconds: number;
}

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

function pollInterval(data: PollingPayload | undefined): number | false {
  if (!data?.page_polling_enabled) return false;
  return Math.max(10, data.recommended_poll_interval_seconds || 60) * 1000;
}

export function OpsRealtimeMonitorPage() {
  const dailyHealthQuery = useQuery({
    queryKey: ["ops", "realtime", "stock-rt-daily", "health"],
    queryFn: () => apiRequest<OpsRealtimeStockRtDailyHealthResponse>(DAILY_HEALTH_API_PATH),
    refetchInterval: (query) => pollInterval(query.state.data),
  });
  const minuteHealthQuery = useQuery({
    queryKey: ["ops", "realtime", "stock-rt-min", "health"],
    queryFn: () => apiRequest<OpsRealtimeStockRtMinHealthResponse>(MINUTE_HEALTH_API_PATH),
    refetchInterval: (query) => pollInterval(query.state.data),
  });
  const etfHealthQuery = useQuery({
    queryKey: ["ops", "realtime", "etf-rt-daily", "health"],
    queryFn: () => apiRequest<OpsRealtimeEtfRtDailyHealthResponse>(ETF_HEALTH_API_PATH),
    refetchInterval: (query) => pollInterval(query.state.data),
  });
  const dailyHealth = dailyHealthQuery.data;
  const minuteHealth = minuteHealthQuery.data;
  const etfHealth = etfHealthQuery.data;

  return (
    <Stack gap="lg">
      <Text c="dimmed" size="sm">
        这里监控实时行情流本身：collector 是否应当采集、Redis 当前批次是否可读、以及最近一次上游请求和写入是否正常。
      </Text>

      {dailyHealthQuery.isLoading || minuteHealthQuery.isLoading || etfHealthQuery.isLoading ? <Loader size="sm" /> : null}
      {dailyHealthQuery.error ? (
        <Alert color="error" title="读取股票实时日线监控失败">
          {dailyHealthQuery.error instanceof Error ? dailyHealthQuery.error.message : "未知错误"}
        </Alert>
      ) : null}
      {minuteHealthQuery.error ? (
        <Alert color="error" title="读取股票实时分钟监控失败">
          {minuteHealthQuery.error instanceof Error ? minuteHealthQuery.error.message : "未知错误"}
        </Alert>
      ) : null}
      {etfHealthQuery.error ? (
        <Alert color="error" title="读取 ETF 实时日线监控失败">
          {etfHealthQuery.error instanceof Error ? etfHealthQuery.error.message : "未知错误"}
        </Alert>
      ) : null}

      {dailyHealth ? <DailyFeedSection health={dailyHealth} /> : null}
      {minuteHealth ? <MinuteFeedSection health={minuteHealth} /> : null}
      {etfHealth ? <EtfFeedSection health={etfHealth} /> : null}
    </Stack>
  );
}

function DailyFeedSection({ health }: { health: OpsRealtimeStockRtDailyHealthResponse }) {
  return (
    <>
      <SectionCard
        title="股票实时日线"
        description="页面只读取实时流健康 API，不触发采集、不请求 Tushare、不读 Redis key。"
        action={
          <Group gap="xs">
            <StatusBadge value={health.status} />
            <PollingBadge enabled={health.page_polling_enabled} />
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
        <AlertBar tone="error" title="股票实时日线暂不可用">
          {health.last_error_message || "当前没有可读 Redis 批次，或 Redis 状态层不可连接。"}
        </AlertBar>
      ) : null}

      {health.status === "stale" ? (
        <AlertBar tone="warning" title="股票实时日线刷新滞后">
          当前批次年龄为 {formatSeconds(health.current_batch_age_seconds)}，已超过 {health.stale_after_seconds} 秒阈值。
        </AlertBar>
      ) : null}

      <Grid>
        <Grid.Col span={{ base: 12, lg: 6 }}>
          <SectionCard title="日线采集与上游" description="collector 和 Tushare 请求侧状态。">
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
          <SectionCard title="日线 Redis 当前批次" description="API 只读取 current pointer 指向的同一批次。">
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

      <StreamSection
        title="日线 Stream 事件"
        description="批次事件用于观测，逐股票变化事件为后续 WebSocket 预留。"
        lastBatchEventId={health.last_batch_event_id}
        lastDeltaEventId={health.last_delta_event_id}
        deltaCountLastBatch={health.delta_count_last_batch}
      />
    </>
  );
}

function MinuteFeedSection({ health }: { health: OpsRealtimeStockRtMinHealthResponse }) {
  const totalInvalidCount = health.items.reduce((sum, item) => sum + item.invalid_count, 0);
  return (
    <SectionCard
      title="股票实时分钟"
      description="页面只读取分钟健康 API；五个频率由后端配置和 health items 返回，前端不自行推导。"
      action={
        <Group gap="xs">
          <StatusBadge value={health.status} />
          <Badge variant="light" color={health.enabled ? "info" : "neutral"}>
            {health.enabled ? "分钟采集已启用" : "分钟采集未启用"}
          </Badge>
          <PollingBadge enabled={health.page_polling_enabled} />
        </Group>
      }
    >
      <Stack gap="md">
        <Grid>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <StatCard
              label="频率数量"
              value={`${health.items.length} 个`}
              hint={`配置频率：${health.configured_freqs.join(" / ") || "—"}`}
              hintDisplay="inline"
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <StatCard
              label="支持频率"
              value={`${health.supported_freqs.length} 个`}
              hint={health.supported_freqs.join(" / ")}
              hintDisplay="inline"
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <StatCard
              label="页面刷新"
              value={health.page_polling_enabled ? "局部刷新中" : "不轮询"}
              hint={`建议间隔：${health.recommended_poll_interval_seconds} 秒`}
              hintDisplay="inline"
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <StatCard
              label="无效行"
              value={formatNumber(totalInvalidCount)}
              hint="来自后端 health 的 invalid_count 汇总"
              hintDisplay="inline"
            />
          </Grid.Col>
        </Grid>

        {health.items.length === 0 ? (
          <AlertBar tone="warning" title="没有分钟频率状态">
            当前 health API 没有返回任何频率项，请先检查后端实时分钟配置。
          </AlertBar>
        ) : null}

        <Grid>
          {health.items.map((item) => (
            <Grid.Col key={item.feed_key} span={{ base: 12, lg: 6, xl: 4 }}>
              <MinuteFeedCard item={item} />
            </Grid.Col>
          ))}
        </Grid>
      </Stack>
    </SectionCard>
  );
}

function EtfFeedSection({ health }: { health: OpsRealtimeEtfRtDailyHealthResponse }) {
  return (
    <>
      <SectionCard
        title="ETF 实时日线"
        description="Redis 保存源端 ETF 批次事实；活跃池命中只用于运营观察，不在采集阶段裁剪。"
        action={
          <Group gap="xs">
            <StatusBadge value={health.status} />
            <Badge variant="light" color={health.enabled ? "info" : "neutral"}>
              {health.enabled ? "ETF 采集已启用" : "ETF 采集未启用"}
            </Badge>
            <PollingBadge enabled={health.page_polling_enabled} />
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
              label="源端快照"
              value={formatNumber(health.source_snapshot_count)}
              hint={`源端返回：${formatNumber(health.source_row_count)} 行`}
              hintDisplay="inline"
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <StatCard
              label="活跃池命中"
              value={`${formatNumber(health.active_snapshot_count)} / ${formatNumber(health.active_pool_count)}`}
              hint="当前批次命中 ETF 活跃池数量 / 活跃池总数"
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
        <AlertBar tone="error" title="ETF 实时日线暂不可用">
          {health.last_error_message || "当前没有可读 Redis 批次，或 Redis 状态层不可连接。"}
        </AlertBar>
      ) : null}

      {health.status === "stale" ? (
        <AlertBar tone="warning" title="ETF 实时日线刷新滞后">
          当前批次年龄为 {formatSeconds(health.current_batch_age_seconds)}，已超过 {health.stale_after_seconds} 秒阈值。
        </AlertBar>
      ) : null}

      {health.invalid_count > 0 ? (
        <AlertBar tone="warning" title="ETF 实时日线存在无效行">
          {formatNumber(health.invalid_count)} 行；{formatInvalidReasonCounts(health.invalid_reason_counts)}
        </AlertBar>
      ) : null}

      <Grid>
        <Grid.Col span={{ base: 12, lg: 6 }}>
          <SectionCard title="ETF 采集与源端" description="沪深两段请求全部成功后，才会发布一个 Redis 批次。">
            <OpsTable>
              <Table.Tbody>
                <InfoRow label="Feed" value={`${health.display_name}（${health.feed_key}）`} />
                <InfoRow label="Collector" value={health.collector_running ? "运行中" : "未观测到运行"} />
                <InfoRow label="Collector ID" value={health.collector_id || "—"} />
                <InfoRow label="最近请求" value={formatDateTimeLabel(health.last_request_at)} />
                <InfoRow label="最近成功" value={formatDateTimeLabel(health.last_success_at)} />
                <InfoRow label="源端耗时" value={formatDurationMs(health.source_elapsed_ms)} />
                <InfoRow label="分段行数" value={formatSegmentCounts(health.segment_counts)} />
                <InfoRow label="最近错误" value={health.last_error_message || "—"} />
              </Table.Tbody>
            </OpsTable>
          </SectionCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, lg: 6 }}>
          <SectionCard title="ETF Redis 当前批次" description="源端全量批次保留，活跃池命中单独统计。">
            <OpsTable>
              <Table.Tbody>
                <InfoRow label="Redis 连接" value={health.redis_connected ? "可连接" : "不可连接"} />
                <InfoRow label="当前批次" value={health.current_batch_id || "—"} />
                <InfoRow label="批次年龄" value={formatSeconds(health.current_batch_age_seconds)} />
                <InfoRow label="批次接收时间" value={formatDateTimeLabel(health.current_batch_received_at)} />
                <InfoRow label="批次发布时间" value={formatDateTimeLabel(health.current_batch_published_at)} />
                <InfoRow label="Redis 写入耗时" value={formatDurationMs(health.write_elapsed_ms)} />
                <InfoRow label="保留策略" value={`${formatNumber(health.snapshot_ttl_seconds)} 秒 / ${health.keep_recent_batches} 批`} />
              </Table.Tbody>
            </OpsTable>
          </SectionCard>
        </Grid.Col>
      </Grid>

      <StreamSection
        title="ETF Stream 事件"
        description="ETF feed 独立写入批次事件和变化事件，为后续 WebSocket 保留基础。"
        lastBatchEventId={health.last_batch_event_id}
        lastDeltaEventId={health.last_delta_event_id}
        deltaCountLastBatch={health.delta_count_last_batch}
      />
    </>
  );
}

function MinuteFeedCard({ item }: { item: OpsRealtimeStockRtMinHealthItem }) {
  return (
    <SectionCard
      title={`${item.freq} 分钟`}
      description={item.feed_key}
      action={
        <Group gap="xs">
          <StatusBadge value={item.status} />
          <Badge variant="light" color={item.enabled ? "info" : "neutral"}>
            {item.enabled ? "已启用" : "已停用"}
          </Badge>
        </Group>
      }
    >
      <Stack gap="md">
        <Grid>
          <Grid.Col span={{ base: 12, sm: 6 }}>
            <StatCard
              label="采集状态"
              value={formatCollectionStatusLabel(item.collection_status)}
              hint={`采集窗口：${item.collection_sessions.join(" / ")}`}
              hintDisplay="inline"
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, sm: 6 }}>
            <StatCard
              label="当前批次"
              value={item.current_batch_id || "—"}
              hint={`批次年龄：${formatSeconds(item.current_batch_age_seconds)}`}
              hintDisplay="inline"
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, sm: 6 }}>
            <StatCard
              label="快照数量"
              value={formatNumber(item.snapshot_count)}
              hint={`源端返回：${formatNumber(item.source_row_count)} 行`}
              hintDisplay="inline"
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, sm: 6 }}>
            <StatCard
              label="限速"
              value={`${item.request_count_last_minute}/${item.max_calls_per_minute}`}
              hint="最近一分钟请求数 / feed 级上限"
              hintDisplay="inline"
            />
          </Grid.Col>
        </Grid>

        {item.status === "unavailable" ? (
          <AlertBar tone="error" title={`${item.freq} 暂不可用`}>
            {item.last_error_message || "当前没有可读 Redis 批次，或 Redis 状态层不可连接。"}
          </AlertBar>
        ) : null}

        {item.status === "stale" ? (
          <AlertBar tone="warning" title={`${item.freq} 刷新滞后`}>
            当前批次年龄为 {formatSeconds(item.current_batch_age_seconds)}，已超过 {item.stale_after_seconds} 秒阈值。
          </AlertBar>
        ) : null}

        {item.invalid_count > 0 ? (
          <AlertBar tone="warning" title={`${item.freq} 存在无效行`}>
            {formatNumber(item.invalid_count)} 行；{formatInvalidReasonCounts(item.invalid_reason_counts)}
          </AlertBar>
        ) : null}

        <OpsTable>
          <Table.Tbody>
            <InfoRow label="Collector" value={item.collector_running ? "运行中" : "未观测到运行"} />
            <InfoRow label="Collector ID" value={item.collector_id || "—"} />
            <InfoRow label="最近请求" value={formatDateTimeLabel(item.last_request_at)} />
            <InfoRow label="最近成功" value={formatDateTimeLabel(item.last_success_at)} />
            <InfoRow label="最近错误" value={item.last_error_message || "—"} />
            <InfoRow label="Redis 连接" value={item.redis_connected ? "可连接" : "不可连接"} />
            <InfoRow label="源端耗时" value={formatDurationMs(item.source_elapsed_ms)} />
            <InfoRow label="Redis 写入耗时" value={formatDurationMs(item.write_elapsed_ms)} />
            <InfoRow label="批次接收时间" value={formatDateTimeLabel(item.current_batch_received_at)} />
            <InfoRow label="批次发布时间" value={formatDateTimeLabel(item.current_batch_published_at)} />
          </Table.Tbody>
        </OpsTable>

        <StreamSection
          title={`${item.freq} Stream 事件`}
          description="分钟 feed 独立写入批次事件和变化事件。"
          lastBatchEventId={item.last_batch_event_id}
          lastDeltaEventId={item.last_delta_event_id}
          deltaCountLastBatch={item.delta_count_last_batch}
        />
      </Stack>
    </SectionCard>
  );
}

function StreamSection({
  title,
  description,
  lastBatchEventId,
  lastDeltaEventId,
  deltaCountLastBatch,
}: {
  title: string;
  description: string;
  lastBatchEventId: string | null;
  lastDeltaEventId: string | null;
  deltaCountLastBatch: number;
}) {
  return (
    <SectionCard title={title} description={description}>
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
                {lastBatchEventId || "—"}
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
                {lastDeltaEventId || "—"}
              </OpsTableCellText>
            </OpsTableCell>
            <OpsTableCell align="left" width="36%">
              <OpsTableCellText size="sm">本批变化股票 {formatNumber(deltaCountLastBatch)} 只。</OpsTableCellText>
            </OpsTableCell>
          </Table.Tr>
        </Table.Tbody>
      </OpsTable>
    </SectionCard>
  );
}

function PollingBadge({ enabled }: { enabled: boolean }) {
  return (
    <Badge variant="light" color={enabled ? "info" : "neutral"}>
      {enabled ? "页面局部刷新中" : "页面不轮询"}
    </Badge>
  );
}

function formatInvalidReasonCounts(counts: Record<string, number>): string {
  const entries = Object.entries(counts);
  if (entries.length === 0) return "暂无原因分布";
  return entries.map(([reason, count]) => `${reason} ${formatNumber(count)} 条`).join(" / ");
}

function formatSegmentCounts(counts: Record<string, number>): string {
  const entries = Object.entries(counts);
  if (entries.length === 0) return "—";
  return entries.map(([segment, count]) => `${segment} ${formatNumber(count)} 行`).join(" / ");
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
