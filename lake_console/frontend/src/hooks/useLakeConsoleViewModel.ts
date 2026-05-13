import type { DatasetRiskItem, DatasetSummary, LakeStatus } from "../types";

type UseLakeConsoleViewModelInput = {
  datasets: DatasetSummary[];
  selectedDatasetKey: string;
  status: LakeStatus | null;
};

export function useLakeConsoleViewModel({ datasets, selectedDatasetKey, status }: UseLakeConsoleViewModelInput) {
  const selectedDataset = datasets.find((dataset) => dataset.dataset_key === selectedDatasetKey) ?? datasets[0] ?? null;
  const allDatasetRisks: DatasetRiskItem[] = datasets.flatMap((dataset) => [
    ...dataset.risks.map((risk) => ({ ...risk, datasetKey: dataset.dataset_key, datasetName: dataset.display_name })),
    ...dataset.node_summaries.flatMap((node) =>
      node.risks.map((risk) => ({ ...risk, datasetKey: dataset.dataset_key, datasetName: `${dataset.display_name} / ${node.node_name}` })),
    ),
  ]);

  return {
    allDatasetRisks,
    isStatusLoading: status === null,
    selectedDataset,
  };
}
