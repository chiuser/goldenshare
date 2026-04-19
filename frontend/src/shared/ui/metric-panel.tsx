import { Group, Paper, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";


interface MetricPanelProps {
  label: string;
  children: ReactNode;
  minHeight?: number;
  align?: "start" | "end";
}

export function MetricPanel({
  label,
  children,
  minHeight = 132,
  align = "end",
}: MetricPanelProps) {
  return (
    <Paper withBorder radius="md" p="md" style={{ minHeight, height: "100%" }}>
      <Stack gap={8} style={{ height: "100%", justifyContent: "space-between" }}>
        <Text c="dimmed" size="sm" fw={600}>
          {label}
        </Text>
        <Group justify={align === "start" ? "flex-start" : "flex-end"} align="flex-end">
          {children}
        </Group>
      </Stack>
    </Paper>
  );
}
