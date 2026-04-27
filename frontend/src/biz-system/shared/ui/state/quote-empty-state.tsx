import { Alert, Button, Stack, Text } from "@mantine/core";

interface QuoteEmptyStateProps {
  onRetry: () => void;
}

export function QuoteEmptyState({ onRetry }: QuoteEmptyStateProps) {
  return (
    <Alert color="yellow" title="暂无行情数据">
      <Stack gap="xs">
        <Text size="sm">当前标的在所选周期下没有可展示数据。请调整标的、周期或稍后重试。</Text>
        <Button size="xs" variant="light" onClick={onRetry}>
          重新加载
        </Button>
      </Stack>
    </Alert>
  );
}
