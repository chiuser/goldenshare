import type { ReactNode } from "react";

export type DataTableColumn<T> = {
  className?: string;
  header: string;
  key: string;
  render: (row: T) => ReactNode;
};

type DataTableCardProps<T> = {
  columns: DataTableColumn<T>[];
  empty: ReactNode;
  getRowKey: (row: T) => string;
  label: string;
  rowTone?: (row: T) => "default" | "selected" | "warning" | "error";
  rows: T[];
};

export function DataTableCard<T>({
  columns,
  empty,
  getRowKey,
  label,
  rowTone,
  rows,
}: DataTableCardProps<T>) {
  if (!rows.length) {
    return <>{empty}</>;
  }

  return (
    <div className="data-table-card">
      <table aria-label={label}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th className={column.className} key={column.key} scope="col">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const tone = rowTone?.(row) ?? "default";
            return (
              <tr className={tone === "default" ? undefined : `row-${tone}`} key={getRowKey(row)}>
                {columns.map((column) => (
                  <td className={column.className} key={column.key}>
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
