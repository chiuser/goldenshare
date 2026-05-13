import { useEffect, useState } from "react";
import { loadCommandExamples, loadDatasets, loadLakeOverview, loadLakeStatus, loadPartitions } from "../services/lakeApi";
import type { CommandExampleGroup, DatasetSummary, LakeOverview, LakeStatus, PartitionSummary } from "../types";

export function useLakeConsoleData() {
  const [status, setStatus] = useState<LakeStatus | null>(null);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [overview, setOverview] = useState<LakeOverview | null>(null);
  const [commandGroups, setCommandGroups] = useState<CommandExampleGroup[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadInitialData() {
      try {
        const [statusPayload, overviewPayload, datasetItems] = await Promise.all([loadLakeStatus(), loadLakeOverview(), loadDatasets()]);
        if (!cancelled) {
          setStatus(statusPayload);
          setOverview(overviewPayload);
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
    overview,
    status,
  };
}

export function useDatasetPartitions(selectedDatasetKey: string, selectedNodeKey: string) {
  const [partitions, setPartitions] = useState<PartitionSummary[]>([]);
  const [partitionError, setPartitionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadDatasetPartitions() {
      if (!selectedDatasetKey || !selectedNodeKey) {
        setPartitions([]);
        return;
      }
      try {
        const partitionItems = await loadPartitions(selectedDatasetKey, selectedNodeKey);
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
  }, [selectedDatasetKey, selectedNodeKey]);

  return {
    partitionError,
    partitions,
  };
}
