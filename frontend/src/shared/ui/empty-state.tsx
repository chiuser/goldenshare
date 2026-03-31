import { Center, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";


interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <Center py="xl">
      <Stack gap="xs" align="center">
        <Text fw={700}>{title}</Text>
        {description ? (
          <Text c="dimmed" size="sm" ta="center" maw={420}>
            {description}
          </Text>
        ) : null}
        {action}
      </Stack>
    </Center>
  );
}
