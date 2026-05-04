import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./components/AppShell";
import { EmptyState } from "./components/EmptyState";
import { useDatasetPartitions, useLakeConsoleData } from "./hooks/useLakeConsoleData";
import { useLakeConsoleSelection } from "./hooks/useLakeConsoleSelection";
import { CommandExamplesPage } from "./pages/CommandExamplesPage";
import { DatasetDetailPage } from "./pages/DatasetDetailPage";
import { DatasetOverviewPage } from "./pages/DatasetOverviewPage";
import { RiskPage } from "./pages/RiskPage";
import "./styles.css";

function App() {
  const initialData = useLakeConsoleData();
  const selection = useLakeConsoleSelection({
    commandGroups: initialData.commandGroups,
    datasets: initialData.datasets,
  });
  const { commandError, commandGroups, datasets, error, status } = initialData;
  const { partitionError, partitions } = useDatasetPartitions(selection.selectedDatasetKey);
  const pageError = error ?? partitionError;

  const selectedDataset = datasets.find((dataset) => dataset.dataset_key === selection.selectedDatasetKey) ?? datasets[0] ?? null;
  const readyDatasets = datasets.filter((dataset) => dataset.file_count > 0).length;
  const totalFiles = datasets.reduce((sum, dataset) => sum + dataset.file_count, 0);
  const totalBytes = datasets.reduce((sum, dataset) => sum + dataset.total_bytes, 0);
  const riskCount = datasets.reduce((sum, dataset) => sum + dataset.risks.length, 0) + (status?.risks.length ?? 0);
  const allDatasetRisks = datasets.flatMap((dataset) =>
    dataset.risks.map((risk) => ({ ...risk, datasetKey: dataset.dataset_key, datasetName: dataset.display_name })),
  );

  return (
    <AppShell activePage={selection.activePage} initialized={Boolean(status?.path.initialized)} onNavigate={selection.setActivePage}>
      {pageError ? <div className="alert error">API 加载失败：{pageError}</div> : null}

      {selection.activePage === "datasets" ? (
        <DatasetOverviewPage
          datasets={datasets}
          readyDatasets={readyDatasets}
          riskCount={riskCount}
          status={status}
          totalBytes={totalBytes}
          totalFiles={totalFiles}
          onOpenDetail={selection.openDatasetDetail}
        />
      ) : null}

      {selection.activePage === "datasetDetail" ? (
        selectedDataset ? (
          <DatasetDetailPage
            dataset={selectedDataset}
            partitions={partitions}
            onBack={() => selection.setActivePage("datasets")}
          />
        ) : (
          <EmptyState title="未选择数据集" description="请先返回数据集总览选择数据集。" />
        )
      ) : null}

      {selection.activePage === "commands" ? (
        <CommandExamplesPage
          commandError={commandError}
          commandGroups={commandGroups}
          selectedCommandGroupKey={selection.selectedCommandGroupKey}
          selectedCommandItemKey={selection.selectedCommandItemKey}
          onSelectGroup={selection.selectCommandGroup}
          onSelectItem={selection.setSelectedCommandItemKey}
        />
      ) : null}

      {selection.activePage === "risks" ? (
        <RiskPage datasetRisks={allDatasetRisks} status={status} />
      ) : null}
    </AppShell>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
