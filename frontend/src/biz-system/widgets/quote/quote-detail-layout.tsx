import { Stack } from "@mantine/core";
import type { ReactNode } from "react";

interface QuoteDetailLayoutProps {
  header: ReactNode;
  chart: ReactNode;
  related: ReactNode;
}

export function QuoteDetailLayout({ header, chart, related }: QuoteDetailLayoutProps) {
  return (
    <Stack gap="md">
      {header}
      {chart}
      {related}
    </Stack>
  );
}
