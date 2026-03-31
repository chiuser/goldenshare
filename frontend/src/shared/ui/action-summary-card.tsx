import { Code, Group, Paper, Stack, Text } from "@mantine/core";

import { HelpTip } from "./help-tip";


interface ActionSummaryRow {
  label: string;
  value: string | number | null | undefined;
}

interface ActionSummaryCardProps {
  title: string;
  description?: string;
  rows: ActionSummaryRow[];
}

export function ActionSummaryCard({ title, description, rows }: ActionSummaryCardProps) {
  const visibleRows = rows.filter((row) => row.value !== undefined);

  if (!visibleRows.length) {
    return null;
  }

  return (
    <Paper withBorder radius="lg" p="md" bg="rgba(255,255,255,0.62)">
      <Stack gap="xs">
        <Group gap={6} align="center">
          <Text fw={700}>{title}</Text>
          {description ? <HelpTip label={description} /> : null}
        </Group>
        {visibleRows.map((row) => (
          <Group key={row.label} justify="space-between" align="flex-start" gap="md">
            <Text c="dimmed" size="sm">
              {row.label}
            </Text>
            <Code>{row.value === null || row.value === "" ? "-" : String(row.value)}</Code>
          </Group>
        ))}
      </Stack>
    </Paper>
  );
}
