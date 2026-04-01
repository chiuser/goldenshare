import { Group, Table, Text, type GroupProps, type TableProps, type TextProps } from "@mantine/core";
import type { PropsWithChildren } from "react";

const headerCellStyle = { textAlign: "center" as const, fontSize: "1rem" };
const bodyCellStyle = { textAlign: "center" as const };

export function OpsTable(props: TableProps) {
  return <Table highlightOnHover striped {...props} />;
}

export function OpsTableHeaderCell({ children }: PropsWithChildren) {
  return <Table.Th style={headerCellStyle}>{children}</Table.Th>;
}

export function OpsTableCell({ children }: PropsWithChildren) {
  return <Table.Td style={bodyCellStyle}>{children}</Table.Td>;
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
