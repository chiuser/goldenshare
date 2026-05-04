import { useEffect, useState } from "react";
import type { ActivePage } from "../components/AppShell";
import type { CommandExampleGroup, DatasetSummary } from "../types";

type UseLakeConsoleSelectionInput = {
  commandGroups: CommandExampleGroup[];
  datasets: DatasetSummary[];
};

export function useLakeConsoleSelection({ commandGroups, datasets }: UseLakeConsoleSelectionInput) {
  const [selectedDatasetKey, setSelectedDatasetKey] = useState<string>("stk_mins");
  const [activePage, setActivePage] = useState<ActivePage>("datasets");
  const [selectedCommandGroupKey, setSelectedCommandGroupKey] = useState<string>("");
  const [selectedCommandItemKey, setSelectedCommandItemKey] = useState<string>("");

  useEffect(() => {
    const preferred = datasets.find((dataset) => dataset.dataset_key === selectedDatasetKey);
    if (!preferred && datasets[0]) {
      setSelectedDatasetKey(datasets[0].dataset_key);
    }
  }, [datasets, selectedDatasetKey]);

  useEffect(() => {
    if (!commandGroups.length) {
      return;
    }
    const firstGroup = commandGroups[0];
    setSelectedCommandGroupKey((current) => (commandGroups.some((group) => group.group_key === current) ? current : firstGroup.group_key));
    setSelectedCommandItemKey((current) => {
      const allItems = commandGroups.flatMap((group) => group.items);
      if (allItems.some((item) => item.item_key === current)) {
        return current;
      }
      return allItems.find((item) => item.item_key === selectedDatasetKey)?.item_key ?? firstGroup.items[0]?.item_key ?? "";
    });
  }, [commandGroups, selectedDatasetKey]);

  function openDatasetDetail(datasetKey: string) {
    setSelectedDatasetKey(datasetKey);
    setActivePage("datasetDetail");
  }

  function selectCommandGroup(groupKey: string) {
    setSelectedCommandGroupKey(groupKey);
    const group = commandGroups.find((item) => item.group_key === groupKey);
    setSelectedCommandItemKey(group?.items[0]?.item_key ?? "");
  }

  return {
    activePage,
    openDatasetDetail,
    selectedCommandGroupKey,
    selectedCommandItemKey,
    selectedDatasetKey,
    selectCommandGroup,
    setActivePage,
    setSelectedCommandItemKey,
  };
}
