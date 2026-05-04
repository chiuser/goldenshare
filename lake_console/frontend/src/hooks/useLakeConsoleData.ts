import { useEffect, useState } from "react";
import { loadCommandExamples, loadDatasets, loadLakeStatus, loadPartitions } from "../services/lakeApi";
import type { CommandExampleGroup, DatasetSummary, LakeStatus, PartitionSummary } from "../types";

export function useLakeConsoleData() {
  const [status, setStatus] = useState<LakeStatus | null>(null);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [commandGroups, setCommandGroups] = useState<CommandExampleGroup[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadInitialData() {
      try {
        const [statusPayload, datasetItems] = await Promise.all([loadLakeStatus(), loadDatasets()]);
        if (!cancelled) {
          setStatus(statusPayload);
          setDatasets(datasetItems);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "未知错误");
        }
      }
    }
    void loadInitialData();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadCommandGroups() {
      try {
        const groups = await loadCommandExamples();
        if (!cancelled) {
          setCommandGroups(groups);
        }
      } catch (caught) {
        if (!cancelled) {
          setCommandError(caught instanceof Error ? caught.message : "未知错误");
        }
      }
    }
    void loadCommandGroups();
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    commandError,
    commandGroups,
    datasets,
    error,
    status,
  };
}

export function useDatasetPartitions(selectedDatasetKey: string) {
  const [partitions, setPartitions] = useState<PartitionSummary[]>([]);
  const [partitionError, setPartitionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadDatasetPartitions() {
      if (!selectedDatasetKey) {
        setPartitions([]);
        return;
      }
      try {
        const partitionItems = await loadPartitions(selectedDatasetKey);
        if (!cancelled) {
          setPartitions(partitionItems.slice(0, 24));
          setPartitionError(null);
        }
      } catch (caught) {
        if (!cancelled) {
          setPartitionError(caught instanceof Error ? caught.message : "未知错误");
        }
      }
    }
    void loadDatasetPartitions();
    return () => {
      cancelled = true;
    };
  }, [selectedDatasetKey]);

  return {
    partitionError,
    partitions,
  };
}
