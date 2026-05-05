import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./components/AppShell";
import { EmptyState } from "./components/EmptyState";
import { ErrorStateBlock } from "./components/ErrorStateBlock";
import { useDatasetPartitions, useLakeConsoleData } from "./hooks/useLakeConsoleData";
import { useLakeConsoleSelection } from "./hooks/useLakeConsoleSelection";
import { useLakeConsoleViewModel } from "./hooks/useLakeConsoleViewModel";
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
  const viewModel = useLakeConsoleViewModel({
    datasets,
    selectedDatasetKey: selection.selectedDatasetKey,
    status,
  });

  return (
    <AppShell activePage={selection.activePage} initialized={Boolean(status?.path.initialized)} onNavigate={selection.setActivePage}>
      {pageError ? <ErrorStateBlock title="API 加载失败" description={pageError} /> : null}

      {selection.activePage === "datasets" ? (
        <DatasetOverviewPage
          datasets={datasets}
          readyDatasets={viewModel.readyDatasets}
          riskCount={viewModel.riskCount}
          status={status}
          totalBytes={viewModel.totalBytes}
          totalFiles={viewModel.totalFiles}
          onOpenDetail={selection.openDatasetDetail}
        />
      ) : null}

      {selection.activePage === "datasetDetail" ? (
        viewModel.selectedDataset ? (
          <DatasetDetailPage
            dataset={viewModel.selectedDataset}
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
        <RiskPage datasetRisks={viewModel.allDatasetRisks} status={status} />
      ) : null}
    </AppShell>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
