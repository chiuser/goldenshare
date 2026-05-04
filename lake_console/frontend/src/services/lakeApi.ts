import type { CommandExampleGroup, DatasetSummary, LakeStatus, PartitionSummary } from "../types";

type DatasetListResponse = {
  items: DatasetSummary[];
};

type PartitionListResponse = {
  items: PartitionSummary[];
};

type CommandExampleResponse = {
  groups: CommandExampleGroup[];
};

async function fetchJson<T>(path: string, errorMessage: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(errorMessage);
  }
  return (await response.json()) as T;
}

export function loadLakeStatus(): Promise<LakeStatus> {
  return fetchJson<LakeStatus>("/api/lake/status", "数据湖控制台 API 请求失败。");
}

export async function loadDatasets(): Promise<DatasetSummary[]> {
  const payload = await fetchJson<DatasetListResponse>("/api/datasets", "数据湖控制台 API 请求失败。");
  return payload.items;
}

export async function loadCommandExamples(): Promise<CommandExampleGroup[]> {
  const payload = await fetchJson<CommandExampleResponse>("/api/lake/command-examples", "命令示例 API 请求失败。");
  return payload.groups;
}

export async function loadPartitions(datasetKey: string): Promise<PartitionSummary[]> {
  const payload = await fetchJson<PartitionListResponse>(
    `/api/partitions?dataset_key=${encodeURIComponent(datasetKey)}`,
    "分区 API 请求失败。",
  );
  return payload.items;
}
