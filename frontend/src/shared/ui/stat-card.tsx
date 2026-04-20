import { Group, Paper, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

import { LabelWithHelp } from "./label-with-help";


interface StatCardProps {
  label: string;
  value: ReactNode;
  hint?: string;
  hintDisplay?: "inline" | "tooltip";
  accent?: ReactNode;
}

export function StatCard({ label, value, hint, hintDisplay = "tooltip", accent }: StatCardProps) {
  return (
    <Paper className="glass-card stat-card" radius="md" p="lg">
      <Stack gap={6}>
        <LabelWithHelp
          label={(
            <Text className="stat-card__label" c="dimmed" fw={600} size="xs">
              {label}
            </Text>
          )}
          help={hintDisplay === "tooltip" ? hint : undefined}
        />
        <Title className="stat-card__value" order={3}>
          {value}
        </Title>
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
