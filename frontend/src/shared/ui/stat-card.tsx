import { Group, Paper, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

import { LabelWithHelp } from "./label-with-help";


interface StatCardProps {
  label: string;
  value: string | number;
  hint?: string;
  hintDisplay?: "inline" | "tooltip";
  accent?: ReactNode;
}

export function StatCard({ label, value, hint, hintDisplay = "tooltip", accent }: StatCardProps) {
  return (
    <Paper className="glass-card" radius="xl" p="lg">
      <Stack gap={6}>
        <LabelWithHelp
          label={(
            <Text c="dimmed" fw={600} size="sm" tt="uppercase">
              {label}
            </Text>
          )}
          help={hintDisplay === "tooltip" ? hint : undefined}
        />
        <Title order={3}>{value}</Title>
        {hint && hintDisplay === "inline" ? (
          <Text size="sm" c="dimmed">
            {hint}
          </Text>
        ) : null}
        {accent}
      </Stack>
    </Paper>
  );
}
