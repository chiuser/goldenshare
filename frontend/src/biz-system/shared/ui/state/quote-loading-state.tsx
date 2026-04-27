import { Paper, Skeleton, Stack } from "@mantine/core";

export function QuoteLoadingState() {
  return (
    <Stack gap="md">
      <Paper withBorder radius="md" p="md">
        <Skeleton height={20} width={280} mb="sm" />
        <Skeleton height={40} width={200} />
      </Paper>
      <Paper withBorder radius="md" p="md">
        <Skeleton height={16} width={120} mb="sm" />
        <Skeleton height={320} />
      </Paper>
    </Stack>
  );
}
