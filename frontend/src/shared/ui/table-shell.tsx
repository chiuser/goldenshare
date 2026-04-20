import { Center, Loader, ScrollArea, Stack } from "@mantine/core";
import type { ReactNode } from "react";

interface TableShellProps {
  children: ReactNode;
  emptyState?: ReactNode;
  hasData: boolean;
  loading?: boolean;
  minWidth?: number | string;
  summary?: ReactNode;
  toolbar?: ReactNode;
}

export function TableShell({
  children,
  emptyState,
  hasData,
  loading = false,
  minWidth = 720,
  summary,
  toolbar,
}: TableShellProps) {
  return (
    <Stack className="table-shell" gap="md">
      {toolbar ? <div className="table-shell__toolbar">{toolbar}</div> : null}
      {summary}
      {loading ? (
        <Center py="lg">
          <Loader aria-label="表格加载中" size="sm" />
        </Center>
      ) : hasData ? (
        <ScrollArea className="table-shell__scroll" offsetScrollbars type="auto">
          <div className="table-shell__inner" style={{ minWidth }}>
            {children}
          </div>
        </ScrollArea>
      ) : (
        emptyState
      )}
    </Stack>
  );
}
