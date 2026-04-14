import { Alert, Paper, Stack, Tabs, Text } from "@mantine/core";
import { useMemo } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";

import { OpsAutomationPage } from "./ops-automation-page";
import { OpsManualSyncPage } from "./ops-manual-sync-page";
import { OpsTasksPage } from "./ops-tasks-page";


type TaskTab = "auto" | "manual" | "records";

function resolveTab(value: unknown): TaskTab {
  if (value === "manual" || value === "records") return value;
  return "auto";
}

export function OpsV21TaskCenterPage() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const activeTab = useMemo(() => resolveTab((search as Record<string, unknown>)?.tab), [search]);

  return (
    <Stack gap="lg">
      <Paper p="md" radius="md">
        <Text fw={800} size="xl">任务中心</Text>
        <Text c="dimmed" size="sm">把自动运行、手动同步、任务记录合并到一个页面里，用 Tab 切换。</Text>
      </Paper>

      <Tabs
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
          <Tabs.Tab value="auto">自动运行</Tabs.Tab>
          <Tabs.Tab value="manual">手动同步</Tabs.Tab>
          <Tabs.Tab value="records">任务记录</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="auto" pt="md">
          <OpsAutomationPage />
        </Tabs.Panel>
        <Tabs.Panel value="manual" pt="md">
          <OpsManualSyncPage />
        </Tabs.Panel>
        <Tabs.Panel value="records" pt="md">
          <OpsTasksPage />
        </Tabs.Panel>
      </Tabs>

      <Alert color="brand" variant="light" title="说明">
        这是 V2.1 的任务中心布局，当前先复用旧能力，后续再分阶段替换为 source/stage 维度更清晰的任务视图。
      </Alert>
    </Stack>
  );
}

