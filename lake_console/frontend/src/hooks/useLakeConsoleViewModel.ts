import type { DatasetRiskItem, DatasetSummary, LakeStatus } from "../types";

type UseLakeConsoleViewModelInput = {
  datasets: DatasetSummary[];
  selectedDatasetKey: string;
  status: LakeStatus | null;
};

export function useLakeConsoleViewModel({ datasets, selectedDatasetKey, status }: UseLakeConsoleViewModelInput) {
  const selectedDataset = datasets.find((dataset) => dataset.dataset_key === selectedDatasetKey) ?? datasets[0] ?? null;
  const readyDatasets = datasets.filter((dataset) => dataset.file_count > 0).length;
  const totalFiles = datasets.reduce((sum, dataset) => sum + dataset.file_count, 0);
  const totalBytes = datasets.reduce((sum, dataset) => sum + dataset.total_bytes, 0);
  const riskCount = datasets.reduce((sum, dataset) => sum + dataset.risks.length, 0) + (status?.risks.length ?? 0);
  const allDatasetRisks: DatasetRiskItem[] = datasets.flatMap((dataset) =>
    dataset.risks.map((risk) => ({ ...risk, datasetKey: dataset.dataset_key, datasetName: dataset.display_name })),
  );

  return {
    allDatasetRisks,
    isStatusLoading: status === null,
    readyDatasets,
    riskCount,
    selectedDataset,
    totalBytes,
    totalFiles,
  };
}
