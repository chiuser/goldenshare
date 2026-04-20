import { Table, type TableProps } from "@mantine/core";
import type { ComponentPropsWithoutRef, Key, ReactNode } from "react";

import { OpsTable, OpsTableCell, OpsTableHeaderCell } from "./ops-table";
import { TableShell } from "./table-shell";

type CellAlign = "left" | "center" | "right";

export interface DataTableColumn<Row> {
  key: string;
  header: ReactNode;
  render: (row: Row) => ReactNode;
  align?: CellAlign;
  width?: string | number;
}

interface DataTableProps<Row> {
  columns: DataTableColumn<Row>[];
  emptyState?: ReactNode;
  getRowKey: (row: Row) => Key;
  getRowProps?: (row: Row) => ComponentPropsWithoutRef<typeof Table.Tr>;
  loading?: boolean;
  minWidth?: number | string;
  rows: Row[];
  summary?: ReactNode;
  tableProps?: TableProps;
  toolbar?: ReactNode;
}

export function DataTable<Row>({
  columns,
  emptyState,
  getRowKey,
  getRowProps,
  loading = false,
  minWidth = 720,
  rows,
  summary,
  tableProps,
  toolbar,
}: DataTableProps<Row>) {
  return (
    <TableShell
      emptyState={emptyState}
      hasData={rows.length > 0}
      loading={loading}
      minWidth={minWidth}
      summary={summary}
      toolbar={toolbar}
    >
      <OpsTable {...tableProps}>
        <Table.Thead>
          <Table.Tr>
            {columns.map((column) => (
              <OpsTableHeaderCell key={column.key} align={column.align} width={column.width}>
                {column.header}
              </OpsTableHeaderCell>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => {
            const rowProps = getRowProps?.(row);
            return (
              <Table.Tr key={getRowKey(row)} {...rowProps}>
                {columns.map((column) => (
                  <OpsTableCell key={column.key} align={column.align} width={column.width}>
                    {column.render(row)}
                  </OpsTableCell>
                ))}
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </OpsTable>
    </TableShell>
  );
}
