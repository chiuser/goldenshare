import { Grid, Group, Stack, type GridColProps, type GridProps } from "@mantine/core";
import type { PropsWithChildren, ReactNode } from "react";

interface FilterBarProps {
  actions?: ReactNode;
  children: ReactNode;
  gutter?: GridProps["gutter"];
}

export function FilterBar({
  actions,
  children,
  gutter = "md",
}: FilterBarProps) {
  return (
    <Stack className="filter-bar" gap="md">
      <Grid align="end" gutter={gutter}>
        {children}
      </Grid>
      {actions ? (
        <Group className="filter-bar__actions" justify="flex-end" gap="xs">
          {actions}
        </Group>
      ) : null}
    </Stack>
  );
}

export function FilterBarItem({
  children,
  span = { base: 12, md: 4 },
}: PropsWithChildren<{ span?: GridColProps["span"] }>) {
  return <Grid.Col span={span}>{children}</Grid.Col>;
}
