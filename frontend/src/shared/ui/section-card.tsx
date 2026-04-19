import { Group, Paper, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";

import { HelpTip } from "./help-tip";


interface SectionCardProps {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}

export function SectionCard({ title, description, action, children }: SectionCardProps) {
  return (
    <Paper className="glass-card section-card" radius="md" p="lg">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" gap="md">
          <Group gap={8} align="center">
            <Text className="section-card__title" fw={600} size="lg" lh={1.35}>
              {title}
            </Text>
            {description ? <HelpTip label={description} maxWidth={360} /> : null}
          </Group>
          {action}
        </Group>
        {children}
      </Stack>
    </Paper>
  );
}
