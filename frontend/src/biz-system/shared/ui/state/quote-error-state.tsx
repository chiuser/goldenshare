import { Alert, Button, Stack, Text } from "@mantine/core";

import { ApiError } from "../../../../shared/api/errors";

interface QuoteErrorStateProps {
  error: Error;
  onRetry: () => void;
}

export function QuoteErrorState({ error, onRetry }: QuoteErrorStateProps) {
  const apiError = error instanceof ApiError ? error : null;
  return (
    <Alert color="red" title="行情加载失败">
      <Stack gap="xs">
        <Text size="sm">{error.message || "当前请求失败，请稍后重试。"}</Text>
        {apiError?.requestId ? (
          <Text size="xs" c="dimmed">
            request_id: {apiError.requestId}
          </Text>
        ) : null}
        <Button size="xs" variant="light" onClick={onRetry}>
          重试
        </Button>
      </Stack>
    </Alert>
  );
}
