import { Group, Stack, Title } from "@mantine/core";
import type { ReactNode } from "react";

import { HelpTip } from "./help-tip";


interface PageHeaderProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function PageHeader({ title, description, action }: PageHeaderProps) {
  return (
    <Group justify="space-between" align="flex-start" gap="md">
      <Stack gap={4}>
        <Group gap={8} align="center">
          <Title order={2}>{title}</Title>
          {description ? <HelpTip label={description} maxWidth={360} size={18} /> : null}
        </Group>
      </Stack>
      {action}
    </Group>
  );
}
