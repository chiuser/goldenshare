import { Group, Table, Text, type GroupProps, type TableProps, type TextProps } from "@mantine/core";
import type { PropsWithChildren } from "react";

type CellAlign = "left" | "center" | "right";

function resolveAlign(align: CellAlign | undefined) {
  return align ?? "center";
}

export function OpsTable(props: TableProps) {
  return (
    <Table
      highlightOnHover
      striped
      horizontalSpacing="md"
      verticalSpacing="sm"
      {...props}
    />
  );
}

export function OpsTableHeaderCell({
  children,
  align,
  width,
}: PropsWithChildren<{ align?: CellAlign; width?: string | number }>) {
  return (
    <Table.Th
      style={{
        textAlign: resolveAlign(align),
        fontSize: "1rem",
        fontWeight: 700,
        width,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </Table.Th>
  );
}

export function OpsTableCell({
  children,
  align,
  width,
}: PropsWithChildren<{ align?: CellAlign; width?: string | number }>) {
  return (
    <Table.Td
      style={{
        textAlign: resolveAlign(align),
        width,
        verticalAlign: "middle",
      }}
    >
      {children}
    </Table.Td>
  );
}

export function OpsTableCellText({ children, ...props }: PropsWithChildren<TextProps>) {
  return (
    <Text size="sm" {...props}>
      {children}
    </Text>
  );
}

export function OpsTableActionGroup({ children, ...props }: PropsWithChildren<GroupProps>) {
  return (
    <Group gap="xs" justify="center" wrap="wrap" {...props}>
      {children}
    </Group>
  );
}
