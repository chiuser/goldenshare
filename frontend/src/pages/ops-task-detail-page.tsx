import {
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Paper,
  Progress,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { IconCheck, IconClock, IconPlayerPause, IconPlayerStop, IconX } from "@tabler/icons-react";
import { useMemo, useState, type ReactNode } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  ExecutionDetailResponse,
  ExecutionEventPayload,
  ExecutionEventsResponse,
  ExecutionProgressReasonSample,
  SyncCodebookResponse,
  ExecutionStepsResponse,
} from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import {
  formatEventTypeLabel,
  formatExecutionResourceLabel,
  formatProgressMessageLabel,
  formatTriggerSourceLabel,
  formatUnitKindLabel,
} from "../shared/ops-display";
import { AlertBar, AlertBarNote } from "../shared/ui/alert-bar";
import { ActivityTimeline } from "../shared/ui/activity-timeline";
import { DataTable, type DataTableColumn } from "../shared/ui/data-table";
import { DetailDrawer } from "../shared/ui/detail-drawer";
import { MetricPanel } from "../shared/ui/metric-panel";
import { OpsTableCellText } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";

function buildRefetchInterval(status: string | undefined) {
  return status === "queued" || status === "running" || status === "canceling" ? 3000 : false;
}

function sortByTimeDesc<T extends { occurred_at?: string; started_at?: string }>(items: T[]) {
  return [...items].sort((left, right) => {
    const leftTime = new Date(left.occurred_at || left.started_at || 0).getTime();
    const rightTime = new Date(right.occurred_at || right.started_at || 0).getTime();
    return rightTime - leftTime;
  });
}

function parseProgressDetails(message: string | null | undefined) {
  const raw = String(message || "").trim();
  if (!raw) {
    return null;
  }
  const ratioMatch = raw.match(/(\d+)\s*\/\s*(\d+)/);
  const kvMatches = [...raw.matchAll(/([a-zA-Z_]+)=([^\s]+)/g)];
  const kv = Object.fromEntries(kvMatches.map((item) => [item[1], item[2]]));
  const unitRaw = kv.unit || kv.unit_kind || null;
  const unitLabel =
    unitRaw === "stock"
      ? "股票"
      : unitRaw === "index"
        ? "指数"
      : unitRaw === "trade_date"
        ? "交易日"
        : unitRaw === "month"
          ? "月份"
          : unitRaw === "board"
            ? "板块"
            : unitRaw === "enum"
              ? "枚举"
            : unitRaw === "code"
              ? "代码"
              : null;
  const stockLabel = kv.ts_code ? `${kv.ts_code}${kv.security_name ? ` ${kv.security_name}` : ""}` : null;
  const indexLabel = kv.index_code ? `${kv.index_code}${kv.index_name ? ` ${kv.index_name}` : ""}` : null;
  const boardCode = kv.board_code || kv.con_code || null;
  const boardLabel = boardCode ? `${boardCode}${kv.board_name ? ` ${kv.board_name}` : ""}` : null;
  const enumLabel = kv.enum_field || kv.enum_value ? `${kv.enum_field || "枚举"}=${kv.enum_value || ""}` : null;
  let cursorLabel: string | null = null;
  if (kv.trade_date) {
    cursorLabel = `当前日期：${kv.trade_date}`;
  } else if (unitRaw === "stock" && stockLabel) {
    cursorLabel = `当前股票：${stockLabel}`;
  } else if (unitRaw === "index" && indexLabel) {
    cursorLabel = `当前指数：${indexLabel}`;
  } else if (unitRaw === "board" && boardLabel) {
    cursorLabel = `当前板块：${boardLabel}`;
  } else if (kv.ts_code) {
    cursorLabel = `当前代码：${stockLabel || kv.ts_code}`;
  } else if (boardLabel) {
    cursorLabel = `当前板块：${boardLabel}`;
  } else if (indexLabel) {
    cursorLabel = `当前指数：${indexLabel}`;
  } else if (kv.code) {
    cursorLabel = `当前代码：${kv.code}`;
  } else if (kv.idx_type) {
    cursorLabel = `当前类型：${kv.idx_type}`;
  } else if (enumLabel) {
    cursorLabel = `当前枚举：${enumLabel}`;
  }
  const fetched = kv.fetched ? Number(kv.fetched) : null;
  const written = kv.written ? Number(kv.written) : null;
  const rejected = kv.rejected ? Number(kv.rejected) : null;
  const unitFetched = kv.unit_fetched ? Number(kv.unit_fetched) : null;
  const unitWritten = kv.unit_written ? Number(kv.unit_written) : null;
  const unitRejected = kv.unit_rejected ? Number(kv.unit_rejected) : null;
  const reasonCounts = parseReasonCountsToken(kv.reasons);
  return {
    raw,
    displayMessage: formatProgressMessageLabel(raw),
    current: ratioMatch ? Number(ratioMatch[1]) : null,
    total: ratioMatch ? Number(ratioMatch[2]) : null,
    unitLabel,
    cursorLabel,
    freqLabel: kv.freq ? `当前频度：${kv.freq}` : null,
    unitFetched: Number.isFinite(unitFetched) ? unitFetched : null,
    unitWritten: Number.isFinite(unitWritten) ? unitWritten : null,
    unitRejected: Number.isFinite(unitRejected) ? unitRejected : null,
    fetched: Number.isFinite(fetched) ? fetched : null,
    written: Number.isFinite(written) ? written : null,
    rejected: Number.isFinite(rejected) ? rejected : null,
    reasonCounts,
    reasonStatsTruncated: kv.reason_stats_truncated === "1",
  };
}

function parseReasonCountsToken(token: string | null | undefined): Record<string, number> {
  const text = String(token || "").trim();
  if (!text) {
    return {};
  }
  const counts: Record<string, number> = {};
  for (const chunk of text.split("|")) {
    const normalized = chunk.trim();
    if (!normalized) {
      continue;
    }
    const separatorIndex = normalized.lastIndexOf(":");
    if (separatorIndex <= 0 || separatorIndex >= normalized.length - 1) {
      continue;
    }
    const reasonKey = normalized.slice(0, separatorIndex).trim();
    const value = Number(normalized.slice(separatorIndex + 1).trim());
    if (!reasonKey || !Number.isFinite(value) || value <= 0) {
      continue;
    }
    counts[reasonKey] = (counts[reasonKey] || 0) + Math.floor(value);
  }
  return counts;
}

function toSafeNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function normalizeReasonCounts(value: unknown): Record<string, number> {
  if (!value || typeof value !== "object") {
    return {};
  }
  const entries = Object.entries(value as Record<string, unknown>);
  const normalized: Record<string, number> = {};
  for (const [reasonKey, rawCount] of entries) {
    const key = String(reasonKey || "").trim();
    const count = toSafeNumber(rawCount);
    if (!key || count === null || count <= 0) {
      continue;
    }
    normalized[key] = Math.floor(count);
  }
  return normalized;
}

function normalizeReasonSamples(value: unknown): ExecutionProgressReasonSample[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const samples: ExecutionProgressReasonSample[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const sample = item as Record<string, unknown>;
    const reasonCode = String(sample.reason_code || "").trim();
    if (!reasonCode) {
      continue;
    }
    const field = String(sample.field || "").trim() || undefined;
    const sampleKey = String(sample.sample_key || "").trim() || undefined;
    const sampleMessage = String(sample.sample_message || "").trim() || undefined;
    samples.push({
      reason_code: reasonCode,
      field,
      sample_key: sampleKey,
      sample_message: sampleMessage,
    });
  }
  return samples;
}

function splitReasonKey(reasonKey: string): { reasonCode: string; field: string | null } {
  const separatorIndex = reasonKey.indexOf(":");
  if (separatorIndex <= 0) {
    return { reasonCode: reasonKey, field: null };
  }
  const reasonCode = reasonKey.slice(0, separatorIndex);
  const field = reasonKey.slice(separatorIndex + 1);
  return { reasonCode, field: field || null };
}

function buildStatusHeadline(detail: ExecutionDetailResponse) {
  if (detail.status === "queued") {
    return {
      title: "任务已经提交",
      description: "系统已经收到你的请求，正在准备开始处理。页面会自动刷新。",
      color: "info" as const,
    };
  }
  if (detail.status === "running") {
    return {
      title: "任务正在处理中",
      description: "系统正在处理你这次同步请求。你可以留在这里等待，也可以稍后回来查看结果。",
      color: "info" as const,
    };
  }
  if (detail.status === "canceling") {
    return {
      title: "任务正在停止中",
      description: detail.progress_message || "系统已收到停止请求，正在结束当前处理。",
      color: "warning" as const,
    };
  }
  if (detail.status === "success") {
    return {
      title: "任务已经处理完成",
      description: detail.summary_message || "这次处理已经顺利完成。",
      color: "success" as const,
    };
  }
  if (detail.status === "failed") {
    return {
      title: "任务处理失败",
      description: detail.summary_message || detail.error_message || "请先查看问题摘要，再决定是否重新提交。",
      color: "error" as const,
    };
  }
  if (detail.status === "canceled") {
    return {
      title: "任务已经停止",
      description: "这次处理已经被停止。如果还需要继续，可以重新提交。",
      color: "neutral" as const,
    };
  }
  return {
    title: "任务已结束",
    description: detail.summary_message || "可以查看下方结果和处理记录。",
    color: "neutral" as const,
  };
}

function buildActionSuggestion(detail: ExecutionDetailResponse) {
  if (detail.status === "queued") {
    return "系统正在安排开始处理。现在不用重复提交，等待几秒后页面会自动刷新。";
  }
  if (detail.status === "running") {
    return "先观察当前进展。如果长时间没有变化，再查看实时处理记录定位卡点。";
  }
  if (detail.status === "canceling") {
    return "系统正在按停止请求收尾。通常会在当前处理单元结束后更新为“已取消”。";
  }
  if (detail.status === "success") {
    return "这次处理已经完成。如果还要处理别的日期范围，可以返回手动同步页继续发起。";
  }
  if (detail.status === "failed") {
    return "先看问题摘要和最近更新，再决定是重新提交，还是复制原参数后调整再发起。";
  }
  if (detail.status === "canceled") {
    return "如果还需要继续处理，建议复制原参数重新发起，避免遗漏处理范围。";
  }
  return "可以继续查看详细过程，确认这次任务的实际结果。";
}

function buildLatestUpdate(
  detail: ExecutionDetailResponse,
  events: ExecutionEventsResponse["items"],
  steps: ExecutionStepsResponse["items"],
) {
  if (detail.status === "success" || detail.status === "failed" || detail.status === "canceled" || detail.status === "partial_success") {
    return {
      time: formatDateTimeLabel(detail.ended_at || detail.last_progress_at || detail.requested_at),
      label: "任务结果",
      message: detail.summary_message || detail.error_message || "任务已结束。",
    };
  }

  if (detail.last_progress_at || detail.progress_message) {
    const parsed = parseProgressDetails(detail.progress_message);
    return {
      time: detail.last_progress_at ? formatDateTimeLabel(detail.last_progress_at) : "刚刚",
      label: "最近进展",
      message: parsed?.displayMessage || detail.progress_message || "系统刚刚写入了新的处理进展。",
    };
  }

  const latestEvent = sortByTimeDesc(events)[0];
  if (latestEvent) {
    return {
      time: formatDateTimeLabel(latestEvent.occurred_at),
      label: formatEventTypeLabel(latestEvent.event_type),
      message: formatProgressMessageLabel(latestEvent.message) || latestEvent.message || "系统已经记录了新的处理进展。",
    };
  }

  const latestStep = [...steps].sort((left, right) => right.sequence_no - left.sequence_no)[0];
  if (latestStep) {
    return {
      time: latestStep.started_at ? formatDateTimeLabel(latestStep.started_at) : "刚刚",
      label: "当前步骤",
      message: latestStep.message || `${latestStep.display_name} ${latestStep.status === "running" ? "正在执行" : "已经更新状态"}`,
    };
  }

  return {
    time: formatDateTimeLabel(detail.requested_at),
    label: "任务创建",
    message: detail.status === "queued" ? "系统已经收到请求，正在准备开始。" : "系统正在等待新的处理进展。",
  };
}

function buildServingLightRefreshUpdate(events: ExecutionEventsResponse["items"]) {
  const targetEvent = [...events]
    .sort((left, right) => new Date(right.occurred_at).getTime() - new Date(left.occurred_at).getTime())
    .find((item) =>
      item.event_type === "serving_light_refreshed"
      || item.event_type === "serving_light_refresh_failed"
      || item.event_type === "serving_light_refresh_skipped",
    );
  if (!targetEvent) {
    return null;
  }
  const touchedRows = Number(targetEvent.payload_json?.touched_rows);
  const normalizedTouchedRows = Number.isFinite(touchedRows) ? touchedRows : null;
  if (targetEvent.event_type === "serving_light_refreshed") {
    return {
      color: "success" as const,
      title: "轻量层刷新成功",
      message: targetEvent.message || "轻量层已完成刷新。",
      touchedRows: normalizedTouchedRows,
      occurredAt: targetEvent.occurred_at,
    };
  }
  if (targetEvent.event_type === "serving_light_refresh_failed") {
    return {
      color: "error" as const,
      title: "轻量层刷新失败",
      message: targetEvent.message || "轻量层刷新失败，请查看系统更新记录。",
      touchedRows: normalizedTouchedRows,
      occurredAt: targetEvent.occurred_at,
    };
  }
  return {
    color: "neutral" as const,
    title: "轻量层刷新已跳过",
    message: targetEvent.message || "本次任务写入为 0，已跳过轻量层刷新。",
    touchedRows: normalizedTouchedRows,
    occurredAt: targetEvent.occurred_at,
  };
}

interface ProgressSnapshot {
  current: number;
  total: number;
  percent: number;
  message: string;
  unitLabel: string;
  cursorLabel: string | null;
  freqLabel: string | null;
  unitFetched: number | null;
  unitWritten: number | null;
  unitRejected: number | null;
  fetched: number | null;
  written: number | null;
  rejected: number | null;
  reasonCounts: Record<string, number>;
  reasonSamples: ExecutionProgressReasonSample[];
  reasonStatsTruncated: boolean;
  reasonStatsTruncateNote: string | null;
  occurredAt: string | null;
}

function extractProgressSnapshot(events: ExecutionEventsResponse["items"]) {
  const progressEvent = [...events]
    .sort((left, right) => new Date(right.occurred_at).getTime() - new Date(left.occurred_at).getTime())
    .find((item) => item.event_type === "step_progress" && (item.payload_json?.progress_message || item.message));
  if (!progressEvent) {
    return null;
  }

  const payload = (progressEvent.payload_json || {}) as ExecutionEventPayload;
  const progressMessage = String(payload.progress_message || progressEvent.message || "");
  const parsedFromText = parseProgressDetails(progressMessage);

  const current = toSafeNumber(payload.progress_current) ?? parsedFromText?.current ?? null;
  const total = toSafeNumber(payload.progress_total) ?? parsedFromText?.total ?? null;
  if (current === null || total === null || total <= 0) {
    return null;
  }

  const fetched = toSafeNumber(payload.rows_fetched) ?? parsedFromText?.fetched ?? null;
  const written = toSafeNumber(payload.rows_written) ?? parsedFromText?.written ?? null;
  let rejected = toSafeNumber(payload.rows_rejected) ?? parsedFromText?.rejected ?? null;

  const reasonCountsFromPayload = normalizeReasonCounts(payload.rejected_reason_counts);
  const reasonCountsFromText = parsedFromText?.reasonCounts || {};
  const reasonCounts = Object.keys(reasonCountsFromPayload).length ? reasonCountsFromPayload : reasonCountsFromText;
  if (Object.keys(reasonCounts).length > 0) {
    const reasonRejected = Object.values(reasonCounts).reduce((sum, value) => sum + value, 0);
    rejected = rejected === null ? reasonRejected : Math.max(rejected, reasonRejected);
  } else if (rejected === null && fetched !== null && written !== null) {
    rejected = Math.max(fetched - written, 0);
  }

  const reasonSamples = normalizeReasonSamples(payload.rejected_reason_samples);
  const reasonStatsTruncated = Boolean(payload.reason_stats_truncated || parsedFromText?.reasonStatsTruncated);
  const truncateNote = typeof payload.reason_stats_truncate_note === "string"
    ? payload.reason_stats_truncate_note
    : null;

  const unitLabel = parsedFromText?.unitLabel || "任务单元";
  const cursorLabel = parsedFromText?.cursorLabel || null;
  const percent = toSafeNumber(payload.progress_percent) ?? Math.max(0, Math.min(100, Math.round((current / total) * 100)));

  return {
    current,
    total,
    percent,
    message: parsedFromText?.displayMessage || formatProgressMessageLabel(progressMessage) || progressMessage,
    unitLabel,
    cursorLabel,
    freqLabel: parsedFromText?.freqLabel || null,
    unitFetched: parsedFromText?.unitFetched ?? null,
    unitWritten: parsedFromText?.unitWritten ?? null,
    unitRejected: parsedFromText?.unitRejected ?? null,
    fetched,
    written,
    rejected,
    reasonCounts,
    reasonSamples,
    reasonStatsTruncated,
    reasonStatsTruncateNote: truncateNote,
    occurredAt: progressEvent.occurred_at,
  };
}

function buildStructuredProgressSnapshot(
  detail: ExecutionDetailResponse,
  events: ExecutionEventsResponse["items"],
): ProgressSnapshot | null {
  const fromEvent = extractProgressSnapshot(events);
  const detailProgress = parseProgressDetails(detail.progress_message);
  if (
    detail.progress_current !== null &&
    detail.progress_current !== undefined &&
    detail.progress_total !== null &&
    detail.progress_total !== undefined &&
    detail.progress_total > 0
  ) {
    const detailPercent = detail.progress_percent ?? Math.round((detail.progress_current / detail.progress_total) * 100);
    const preferDetailProgress = Boolean(fromEvent && detailPercent > fromEvent.percent);
    const current = preferDetailProgress ? detail.progress_current : (fromEvent?.current ?? detail.progress_current);
    const total = preferDetailProgress ? detail.progress_total : (fromEvent?.total ?? detail.progress_total);
    const fetched = preferDetailProgress
      ? (detailProgress?.fetched ?? fromEvent?.fetched ?? null)
      : (fromEvent?.fetched ?? detailProgress?.fetched ?? null);
    const written = preferDetailProgress
      ? (detailProgress?.written ?? fromEvent?.written ?? null)
      : (fromEvent?.written ?? detailProgress?.written ?? null);
    const unitFetched = preferDetailProgress
      ? (detailProgress?.unitFetched ?? fromEvent?.unitFetched ?? null)
      : (fromEvent?.unitFetched ?? detailProgress?.unitFetched ?? null);
    const unitWritten = preferDetailProgress
      ? (detailProgress?.unitWritten ?? fromEvent?.unitWritten ?? null)
      : (fromEvent?.unitWritten ?? detailProgress?.unitWritten ?? null);
    const unitRejected = preferDetailProgress
      ? (detailProgress?.unitRejected ?? fromEvent?.unitRejected ?? null)
      : (fromEvent?.unitRejected ?? detailProgress?.unitRejected ?? null);
    const detailRejected = detailProgress?.rejected ?? null;
    const reasonCounts = preferDetailProgress
      ? (detailProgress?.reasonCounts || {})
      : (fromEvent?.reasonCounts || detailProgress?.reasonCounts || {});
    let rejected = preferDetailProgress
      ? (detailRejected ?? fromEvent?.rejected ?? null)
      : (fromEvent?.rejected ?? detailRejected);
    if (rejected === null && fetched !== null && written !== null) {
      rejected = Math.max(fetched - written, 0);
    }
    if (Object.keys(reasonCounts).length > 0) {
      const reasonRejected = Object.values(reasonCounts).reduce((sum, value) => sum + value, 0);
      rejected = rejected === null ? reasonRejected : Math.max(rejected, reasonRejected);
    }
    return {
      current,
      total,
      percent: preferDetailProgress ? detailPercent : (fromEvent?.percent ?? detailPercent),
      message: preferDetailProgress
        ? (detailProgress?.displayMessage || detail.progress_message || fromEvent?.message || "系统正在持续更新当前进展。")
        : (fromEvent?.message || detailProgress?.displayMessage || detail.progress_message || "系统正在持续更新当前进展。"),
      unitLabel: preferDetailProgress
        ? (detailProgress?.unitLabel || fromEvent?.unitLabel || "任务单元")
        : (fromEvent?.unitLabel || detailProgress?.unitLabel || "任务单元"),
      cursorLabel: preferDetailProgress
        ? (detailProgress?.cursorLabel || null)
        : (fromEvent?.cursorLabel || detailProgress?.cursorLabel || null),
      freqLabel: preferDetailProgress
        ? (detailProgress?.freqLabel || fromEvent?.freqLabel || null)
        : (fromEvent?.freqLabel || detailProgress?.freqLabel || null),
      unitFetched,
      unitWritten,
      unitRejected,
      fetched,
      written,
      rejected,
      reasonCounts,
      reasonSamples: preferDetailProgress ? [] : (fromEvent?.reasonSamples || []),
      reasonStatsTruncated: preferDetailProgress ? false : (fromEvent?.reasonStatsTruncated || false),
      reasonStatsTruncateNote: preferDetailProgress ? null : (fromEvent?.reasonStatsTruncateNote || null),
      occurredAt: preferDetailProgress ? detail.last_progress_at : (fromEvent?.occurredAt || detail.last_progress_at),
    };
  }
  if (fromEvent) {
    return fromEvent;
  }
  return null;
}

function buildLiveResult(
  detail: ExecutionDetailResponse,
  progressSnapshot: ProgressSnapshot | null,
) {
  if (progressSnapshot && progressSnapshot.total > 0) {
    const unitLabel = progressSnapshot.unitLabel || "任务单元";
    const unitWord = unitLabel === "任务单元" ? unitLabel : `${unitLabel}`;
    return {
      value: `${progressSnapshot.current}/${progressSnapshot.total}`,
      hint: `已处理${unitWord} / 全部${unitWord}`,
    };
  }

  if (detail.rows_fetched > 0 || detail.rows_written > 0) {
    return {
      value: `${detail.rows_fetched}/${detail.rows_written}`,
      hint: "读取数量 / 写入数量",
    };
  }

  if (detail.status === "queued") {
    return {
      value: "等待开始",
      hint: "任务已经提交，但还没进入实际处理阶段。",
    };
  }

  if (detail.status === "running") {
    return {
      value: "处理中",
      hint: "任务正在运行，进展写回后会自动显示。",
    };
  }
  if (detail.status === "canceling") {
    return {
      value: "停止中",
      hint: "系统已收到停止请求，正在结束当前处理单元。",
    };
  }

  return {
    value: "暂无结果",
    hint: detail.status === "success" ? "任务执行完成，但没有可汇总的读取/写入数字。" : "这次任务还没有留下可汇总的处理结果。",
  };
}

interface RejectionReasonRow {
  reasonKey: string;
  reasonCode: string;
  field: string | null;
  count: number;
}

function buildRejectionReasonRows(reasonCounts: Record<string, number>): RejectionReasonRow[] {
  return Object.entries(reasonCounts)
    .map(([reasonKey, count]) => {
      const parsed = splitReasonKey(reasonKey);
      return {
        reasonKey,
        reasonCode: parsed.reasonCode,
        field: parsed.field,
        count,
      };
    })
    .filter((item) => item.count > 0)
    .sort((left, right) => right.count - left.count || left.reasonKey.localeCompare(right.reasonKey));
}

function getEventRejectedRows(item: ExecutionEventsResponse["items"][number]): number | null {
  const payload = item.payload_json as ExecutionEventPayload;
  const fromPayload = toSafeNumber(payload.rows_rejected);
  if (fromPayload !== null) {
    return Math.max(fromPayload, 0);
  }
  const parsed = parseProgressDetails(payload.progress_message || item.message || "");
  if (parsed?.rejected !== null && parsed?.rejected !== undefined) {
    return Math.max(parsed.rejected, 0);
  }
  if (parsed && parsed.fetched !== null && parsed.written !== null) {
    return Math.max(parsed.fetched - parsed.written, 0);
  }
  return null;
}

function renderStepStatusIcon(status: string) {
  if (status === "success") {
    return (
      <ThemeIcon color="success" variant="light" radius="md" size="lg">
        <IconCheck size={18} />
      </ThemeIcon>
    );
  }
  if (status === "failed") {
    return (
      <ThemeIcon color="error" variant="light" radius="md" size="lg">
        <IconX size={18} />
      </ThemeIcon>
    );
  }
  if (status === "running") {
    return (
      <ThemeIcon color="info" variant="light" radius="md" size="lg">
        <Loader size={16} />
      </ThemeIcon>
    );
  }
  if (status === "canceling") {
    return (
      <ThemeIcon color="warning" variant="light" radius="md" size="lg">
        <IconPlayerPause size={18} />
      </ThemeIcon>
    );
  }
  if (status === "canceled") {
    return (
      <ThemeIcon color="neutral" variant="light" radius="md" size="lg">
        <IconPlayerStop size={18} />
      </ThemeIcon>
    );
  }
  return (
    <ThemeIcon color="neutral" variant="light" radius="md" size="lg">
      <IconClock size={18} />
    </ThemeIcon>
  );
}

function getStepStatusLabel(status: string) {
  if (status === "running") return "执行中";
  if (status === "success") return "成功";
  if (status === "failed") return "失败";
  if (status === "canceling") return "停止中";
  if (status === "canceled") return "已停止";
  return "等待开始";
}

function renderStepBullet(sequenceNo: number) {
  const palette = ["brand", "info", "success", "warning", "error", "neutral"] as const;
  const color = palette[(sequenceNo - 1) % palette.length];
  return <ThemeIcon color={color} variant="filled" radius="sm" size="sm" />;
}

function DetailSurfaceCard({ children }: { children: ReactNode }) {
  return (
    <Paper withBorder radius="md" p="md">
      {children}
    </Paper>
  );
}

export function OpsTaskDetailPage({ executionId }: { executionId: number }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [reasonDrawerOpened, setReasonDrawerOpened] = useState(false);

  const detailQuery = useQuery({
    queryKey: ["ops", "execution", executionId],
    queryFn: () => apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}`),
    refetchInterval: (query) => buildRefetchInterval(query.state.data?.status),
  });

  const activeStatus = detailQuery.data?.status;

  const stepsQuery = useQuery({
    queryKey: ["ops", "execution", executionId, "steps"],
    queryFn: () => apiRequest<ExecutionStepsResponse>(`/api/v1/ops/executions/${executionId}/steps`),
    refetchInterval: buildRefetchInterval(activeStatus),
  });

  const eventsQuery = useQuery({
    queryKey: ["ops", "execution", executionId, "events"],
    queryFn: () => apiRequest<ExecutionEventsResponse>(`/api/v1/ops/executions/${executionId}/events`),
    refetchInterval: buildRefetchInterval(activeStatus),
  });

  const syncCodebookQuery = useQuery({
    queryKey: ["ops", "sync-codebook"],
    queryFn: () => apiRequest<SyncCodebookResponse>("/api/v1/ops/codebook/sync"),
    staleTime: 5 * 60 * 1000,
  });

  const retryMutation = useMutation({
    mutationFn: () =>
      apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}/retry`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      notifications.show({
        color: "success",
        title: "任务已重新提交",
        message: "系统已经收到新的任务请求。",
      });
      await queryClient.invalidateQueries({ queryKey: ["ops"] });
      await navigate({ to: "/ops/tasks/$executionId", params: { executionId: String(data.id) } });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () =>
      apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}/cancel`, {
        method: "POST",
      }),
    onSuccess: async () => {
      notifications.show({
        color: "success",
        title: "已经请求停止当前任务",
        message: `任务 #${executionId}`,
      });
      await queryClient.invalidateQueries({ queryKey: ["ops", "execution", executionId] });
      await queryClient.invalidateQueries({ queryKey: ["ops", "executions"] });
    },
  });

  const detail = detailQuery.data;
  const steps = stepsQuery.data?.items || [];
  const events = eventsQuery.data?.items || [];
  const sortedEvents = useMemo(() => sortByTimeDesc(events), [events]);
  const eventColumns = useMemo<DataTableColumn<ExecutionEventsResponse["items"][number]>[]>(() => [
    {
      key: "occurred_at",
      header: "时间",
      align: "left",
      width: "20%",
      render: (item) => (
        <OpsTableCellText ff="var(--mantine-font-family-monospace)" fw={500} size="xs">
          {formatDateTimeLabel(item.occurred_at)}
        </OpsTableCellText>
      ),
    },
    {
      key: "event_type",
      header: "更新内容",
      align: "left",
      width: "26%",
      render: (item) => (
        <Group gap="xs">
          <Badge variant="light">{formatEventTypeLabel(item.event_type)}</Badge>
          <StatusBadge value={item.level} />
        </Group>
      ),
    },
    {
      key: "message",
      header: "说明",
      align: "left",
      width: "42%",
      render: (item) => <Text size="sm">{formatProgressMessageLabel(item.message) || item.message || "系统记录了一次新的处理更新。"}</Text>,
    },
    {
      key: "rejected",
      header: "拒绝",
      align: "left",
      width: "12%",
      render: (item) => {
        const rejected = getEventRejectedRows(item);
        if (rejected === null) {
          return <Text size="sm" c="dimmed">—</Text>;
        }
        return rejected > 0
          ? <Badge color="warning" variant="light">{`有拒绝(${rejected})`}</Badge>
          : <Text size="sm" c="dimmed">无拒绝</Text>;
      },
    },
  ], []);
  const progressSnapshot = detail ? buildStructuredProgressSnapshot(detail, events) : null;
  const reasonRows = useMemo(
    () => buildRejectionReasonRows(progressSnapshot?.reasonCounts || {}),
    [progressSnapshot?.reasonCounts],
  );
  const totalRejected = useMemo(
    () => reasonRows.reduce((sum, item) => sum + item.count, 0) || (progressSnapshot?.rejected || 0),
    [progressSnapshot?.rejected, reasonRows],
  );
  const reasonCodebookMap = useMemo(() => {
    const entries = (syncCodebookQuery.data?.reason_codes || []).map((item) => [item.code, item] as const);
    return new Map(entries);
  }, [syncCodebookQuery.data?.reason_codes]);
  const reasonSampleList = useMemo(
    () => progressSnapshot?.reasonSamples || [],
    [progressSnapshot?.reasonSamples],
  );
  const liveResult = detail ? buildLiveResult(detail, progressSnapshot) : null;
  const latestUpdate = detail ? buildLatestUpdate(detail, events, steps) : null;
  const servingLightUpdate = buildServingLightRefreshUpdate(events);
  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Text c="dimmed" size="sm">
            先看当前状态和进展，再决定是继续等待、重新提交，还是展开技术细节排查。
          </Text>
        </Stack>
        <Button variant="light" component="a" href="/app/ops/tasks">
          返回任务记录
        </Button>
      </Group>

      {(detailQuery.isLoading || stepsQuery.isLoading || eventsQuery.isLoading) ? <Loader size="sm" /> : null}
      {detailQuery.error ? (
        <AlertBar tone="error" title="无法读取任务详情">
          {detailQuery.error instanceof Error ? detailQuery.error.message : "未知错误"}
        </AlertBar>
      ) : null}

      {detail ? (
        <>
          <SectionCard
            title={formatExecutionResourceLabel(detail)}
            description="这里先告诉你这次任务现在是什么状态，以及你最常用的处理动作。"
            action={
              <Group gap="xs">
                <Button component="a" href={`/app/ops/manual-sync?from_execution_id=${detail.id}`} variant="light">
                  复制参数
                </Button>
                {detail.status === "failed" ? (
                  <Button onClick={() => retryMutation.mutate()} loading={retryMutation.isPending}>
                    重新提交
                  </Button>
                ) : null}
                {(detail.status === "queued" || detail.status === "running") ? (
                  <Button color="warning" variant="light" onClick={() => cancelMutation.mutate()} loading={cancelMutation.isPending}>
                    停止处理
                  </Button>
                ) : null}
              </Group>
            }
          >
            <AlertBar tone={buildStatusHeadline(detail).color} title={buildStatusHeadline(detail).title}>
              {buildStatusHeadline(detail).description}
            </AlertBar>
            <SimpleGrid cols={{ base: 1, sm: 2, xl: detail.time_scope_label ? 5 : 4 }} spacing="md" verticalSpacing="md">
              <MetricPanel label="当前状态">
                <StatusBadge value={detail.status} size="lg" />
              </MetricPanel>
              <MetricPanel label="发起方式">
                <Text fw={700} size="xl">{formatTriggerSourceLabel(detail.trigger_source)}</Text>
              </MetricPanel>
              {detail.time_scope_label ? (
                <MetricPanel label="处理范围">
                  <Text fw={700} size="xl">{detail.time_scope_label}</Text>
                </MetricPanel>
              ) : null}
              <MetricPanel label="提交时间">
                <Text ff="monospace" fw={700} size="xl">{formatDateTimeLabel(detail.requested_at)}</Text>
              </MetricPanel>
              <MetricPanel label="当前结果">
                <Text fw={700} size="xl">{liveResult?.value || "暂无结果"}</Text>
              </MetricPanel>
            </SimpleGrid>
          </SectionCard>

          <Grid gutter="lg">
            <Grid.Col span={{ base: 12, lg: 7 }}>
              <SectionCard title="当前进展" description="这里只保留最关键的进展信息，帮助你快速判断任务是不是在正常推进。">
                <Stack gap="md">
                  {latestUpdate ? (
                    <AlertBar tone={detail.status === "failed" ? "error" : "info"} title={`最近更新：${latestUpdate.label}`}>
                      <Text size="sm">{latestUpdate.message}</Text>
                      <AlertBarNote>更新时间：{latestUpdate.time}</AlertBarNote>
                    </AlertBar>
                  ) : null}
                  {progressSnapshot ? (
                    <DetailSurfaceCard>
                      <Stack gap={8}>
                      <Group justify="space-between" align="end">
                        <Stack gap={2}>
                          <Text c="dimmed" size="sm">阶段性进度</Text>
                          <Text fw={700} size="xl">{progressSnapshot.current} / {progressSnapshot.total}</Text>
                        </Stack>
                        <Text fw={700} size="lg" c="var(--mantine-color-brand-6)">{progressSnapshot.percent}%</Text>
                      </Group>
                      <Progress value={progressSnapshot.percent} radius="md" size="lg" color="brand" />
                      <Text size="sm" c="dimmed">
                        {`进度单位：${progressSnapshot.unitLabel || "任务单元"}`}
                      </Text>
                      <Text size="sm">{progressSnapshot.message}</Text>
                      {progressSnapshot.cursorLabel ? (
                        <Text size="sm">{progressSnapshot.cursorLabel}</Text>
                      ) : null}
                      {progressSnapshot.freqLabel ? (
                        <Text size="sm">{progressSnapshot.freqLabel}</Text>
                      ) : null}
                      {(progressSnapshot.unitFetched !== null || progressSnapshot.unitWritten !== null || progressSnapshot.unitRejected !== null) ? (
                        <Text size="sm">
                          当前处理对象结果：读取 {progressSnapshot.unitFetched ?? 0} 条，写入 {progressSnapshot.unitWritten ?? 0} 条，拒绝 {progressSnapshot.unitRejected ?? 0} 条
                        </Text>
                      ) : null}
                      {(progressSnapshot.fetched !== null || progressSnapshot.written !== null || progressSnapshot.rejected !== null) ? (
                        <Group justify="space-between" align="center">
                          <Text size="sm">
                            {(progressSnapshot.unitFetched !== null || progressSnapshot.unitWritten !== null || progressSnapshot.unitRejected !== null) ? "累计接口结果" : "当前接口结果"}：读取 {progressSnapshot.fetched ?? 0} 条，写入 {progressSnapshot.written ?? 0} 条，拒绝 {progressSnapshot.rejected ?? 0} 条
                          </Text>
                          {(progressSnapshot.rejected ?? 0) > 0 ? (
                            <Button
                              size="xs"
                              variant="light"
                              onClick={() => setReasonDrawerOpened(true)}
                            >
                              查看原因
                            </Button>
                          ) : null}
                        </Group>
                      ) : null}
                      <Text size="sm" c="dimmed">
                        最近一次进度更新：{formatDateTimeLabel(progressSnapshot.occurredAt)}
                      </Text>
                      </Stack>
                    </DetailSurfaceCard>
                  ) : (
                    (detail.status === "queued" || detail.status === "running" || detail.status === "canceling") ? (
                      <AlertBar title="处理中，等待进展写回">
                        任务正在执行。进度与当前处理对象写回后，这里会自动更新。
                      </AlertBar>
                    ) : (
                      <AlertBar tone={detail.status === "failed" ? "error" : "success"} title="任务已结束">
                        {detail.summary_message || detail.error_message || "任务已结束。"}
                      </AlertBar>
                    )
                  )}
                  {servingLightUpdate ? (
                    <AlertBar tone={servingLightUpdate.color} title={servingLightUpdate.title}>
                      <Text size="sm">{servingLightUpdate.message}</Text>
                      {servingLightUpdate.touchedRows !== null ? (
                        <Text size="sm" mt={6}>刷新行数：{servingLightUpdate.touchedRows}</Text>
                      ) : null}
                      <AlertBarNote>更新时间：{formatDateTimeLabel(servingLightUpdate.occurredAt)}</AlertBarNote>
                    </AlertBar>
                  ) : null}
                  <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                    <DetailSurfaceCard>
                      <Stack gap={4}>
                        <Text c="dimmed" size="sm">当前结果</Text>
                        <Text fw={700}>{liveResult?.value || "暂无结果"}</Text>
                        <Text size="sm" c="dimmed">{liveResult?.hint}</Text>
                      </Stack>
                    </DetailSurfaceCard>
                    <DetailSurfaceCard>
                      <Stack gap={4}>
                        <Text c="dimmed" size="sm">最近更新</Text>
                        <Text fw={700}>{latestUpdate?.time || "刚刚"}</Text>
                        <Text size="sm" c="dimmed">{latestUpdate?.message || "系统正在等待新的处理进展。"}</Text>
                      </Stack>
                    </DetailSurfaceCard>
                  </SimpleGrid>
                </Stack>
              </SectionCard>
            </Grid.Col>

            <Grid.Col span={{ base: 12, lg: 5 }}>
              <Stack gap="md">
                <SectionCard title="建议下一步" description="不要先钻进原始日志。先看这里给出的下一步建议，再决定要不要继续排查。">
                  <Stack gap="sm">
                    <Text>{buildActionSuggestion(detail)}</Text>
                    {detail.status === "failed" ? (
                      <AlertBar tone="error" title="问题摘要">
                        {detail.summary_message || detail.error_message || "系统已经记录到失败，但还没有生成更具体的摘要。你可以查看实时处理记录继续排查。"}
                      </AlertBar>
                    ) : null}
                  </Stack>
                </SectionCard>
              </Stack>
            </Grid.Col>
          </Grid>

          <SectionCard
            title="实时处理记录"
            description="系统更新和步骤明细会直接显示在这里，方便你实时判断处理情况。"
          >
            <Stack gap="md">
              <Text fw={600}>步骤明细</Text>
              {steps.length ? (
                <ActivityTimeline
                  active={steps.findIndex((item) => item.status === "running" || item.status === "canceling")}
                  items={[...steps]
                    .sort((left, right) => left.sequence_no - right.sequence_no)
                    .map((item) => ({
                      id: item.id,
                      title: item.display_name,
                      bullet: renderStepBullet(item.sequence_no),
                      meta: (
                        <Group gap="xs">
                          <Text size="sm" fw={600}>{getStepStatusLabel(item.status)}</Text>
                          {renderStepStatusIcon(item.status)}
                        </Group>
                      ),
                      time: item.started_at ? `开始：${formatDateTimeLabel(item.started_at)}` : "等待开始",
                      body: (
                        <Stack gap={6}>
                          {item.unit_kind ? (
                            <Text size="sm">{`${formatUnitKindLabel(item.unit_kind)}：${item.unit_value || "未提供"}`}</Text>
                          ) : null}
                          {item.message ? <Text size="sm">{item.message}</Text> : null}
                        </Stack>
                      ),
                    }))}
                />
              ) : (
                <Text c="dimmed" size="sm">暂时还没有步骤明细。</Text>
              )}

              <Text fw={600}>系统更新</Text>
              <DataTable
                columns={eventColumns}
                emptyState={<Text c="dimmed" size="sm">暂时还没有更细的系统更新记录。</Text>}
                getRowKey={(item) => item.id}
                minWidth={780}
                rows={sortedEvents}
              />
            </Stack>
          </SectionCard>

          <DetailDrawer
            opened={reasonDrawerOpened && (progressSnapshot?.rejected ?? 0) > 0}
            onClose={() => setReasonDrawerOpened(false)}
            title="拒绝原因详情"
            description="这里展示当前批次写入拒绝的原因分布。"
            size="lg"
          >
            <Stack gap="md">
              <AlertBar tone="warning" title={`本批次拒绝 ${totalRejected} 条`}>
                {reasonRows.length
                  ? "可直接按原因分布定位问题字段或规则，再决定是否重跑。"
                  : "当前只有拒绝总数，暂时还没有更细的结构化原因分布。"}
              </AlertBar>

              {syncCodebookQuery.isError ? (
                <AlertBar tone="warning" title="编码字典加载失败">
                  当前先显示原始原因码。刷新页面后会自动重试拉取字典。
                </AlertBar>
              ) : null}

              {reasonRows.length ? (
                <Stack gap="sm">
                  {reasonRows.map((item) => {
                    const reasonMeta = reasonCodebookMap.get(item.reasonCode);
                    const ratio = totalRejected > 0 ? Math.round((item.count / totalRejected) * 100) : 0;
                    return (
                      <DetailSurfaceCard key={item.reasonKey}>
                        <Stack gap={6}>
                          <Group justify="space-between" align="center">
                            <Text fw={700}>{item.reasonKey}</Text>
                            <Badge variant="light" color="warning">{`${item.count} 条`}</Badge>
                          </Group>
                          <Text size="sm" c={reasonMeta ? undefined : "dimmed"}>
                            {reasonMeta?.label || "未收录码"}
                          </Text>
                          {item.field ? (
                            <Text size="sm" c="dimmed">{`字段：${item.field}`}</Text>
                          ) : null}
                          {reasonMeta?.suggested_action ? (
                            <Text size="sm" c="dimmed">{`建议：${reasonMeta.suggested_action}`}</Text>
                          ) : null}
                          <Text size="sm" c="dimmed">{`占比：${ratio}%`}</Text>
                        </Stack>
                      </DetailSurfaceCard>
                    );
                  })}
                </Stack>
              ) : (
                <Text c="dimmed" size="sm">暂时没有可展示的拒绝原因分布。</Text>
              )}

              {reasonSampleList.length ? (
                <Stack gap="sm">
                  <Text fw={600}>样例</Text>
                  {reasonSampleList.map((sample, index) => (
                    <DetailSurfaceCard key={`${sample.reason_code}-${sample.sample_key || index}`}>
                      <Stack gap={4}>
                        <Text size="sm" fw={600}>{sample.reason_code}</Text>
                        {sample.field ? <Text size="sm" c="dimmed">{`字段：${sample.field}`}</Text> : null}
                        {sample.sample_key ? <Text size="sm" c="dimmed">{`样例键：${sample.sample_key}`}</Text> : null}
                        {sample.sample_message ? <Text size="sm">{sample.sample_message}</Text> : null}
                      </Stack>
                    </DetailSurfaceCard>
                  ))}
                </Stack>
              ) : null}

              {progressSnapshot?.reasonStatsTruncated ? (
                <AlertBar tone="warning" title="原因信息已截断">
                  {progressSnapshot.reasonStatsTruncateNote || "原因过多时系统会自动截断，只保留部分分布。"}
                </AlertBar>
              ) : null}
            </Stack>
          </DetailDrawer>
        </>
      ) : null}
    </Stack>
  );
}
