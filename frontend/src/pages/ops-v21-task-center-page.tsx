import { Stack, Tabs } from "@mantine/core";
import { useMemo } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";

import { OpsAutomationPage } from "./ops-v21-task-auto-tab";
import { OpsManualTaskTab } from "./ops-v21-task-manual-tab";
import { OpsTasksPage } from "./ops-v21-task-records-tab";


type TaskTab = "auto" | "manual" | "records";

function resolveTab(value: unknown): TaskTab {
  if (value === "auto" || value === "manual" || value === "records") return value;
  return "records";
}

export function OpsV21TaskCenterPage() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const activeTab = useMemo(() => resolveTab((search as Record<string, unknown>)?.tab), [search]);

  return (
    <Stack gap="lg">
      <Tabs
        keepMounted={false}
        value={activeTab}
        onChange={(value) => {
          const next = resolveTab(value);
          void navigate({
            to: "/ops/v21/datasets/tasks",
            search: { tab: next },
            replace: true,
          });
        }}
      >
        <Tabs.List>
          <Tabs.Tab value="records">任务记录</Tabs.Tab>
          <Tabs.Tab value="manual">手动任务</Tabs.Tab>
          <Tabs.Tab value="auto">自动运行</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="records" pt="md">
          <OpsTasksPage />
        </Tabs.Panel>
        <Tabs.Panel value="manual" pt="md">
          <OpsManualTaskTab />
        </Tabs.Panel>
        <Tabs.Panel value="auto" pt="md">
          <OpsAutomationPage />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
