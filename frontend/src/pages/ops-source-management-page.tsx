import { Stack, Text, ThemeIcon } from "@mantine/core";
import { IconDatabaseCog } from "@tabler/icons-react";

import { EmptyState } from "../shared/ui/empty-state";
import { SectionCard } from "../shared/ui/section-card";

export function OpsSourceManagementPage() {
  return (
    <Stack gap="lg">
      <SectionCard
        title="数据源管理（新版）"
        description="这是新版多源运维页面的入口。当前阶段先用于承接 BIYING 数据源任务，旧版页面继续可用。"
      >
        <EmptyState
          title="功能建设中"
          description="新版数据源管理将逐步迁移：先接入数据源状态与任务入口，再扩展融合策略和发布控制。"
          action={
            <ThemeIcon variant="light" color="brand" size={36} radius="xl">
              <IconDatabaseCog size={20} />
            </ThemeIcon>
          }
        />
        <Text size="sm" c="dimmed" mt="md">
          当前请继续在“手动同步 / 任务记录”页面执行与查看 BIYING 日线同步任务。
        </Text>
      </SectionCard>
    </Stack>
  );
}
