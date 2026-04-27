import { Alert, Text } from "@mantine/core";

interface QuoteStaleBannerProps {
  reason: string;
}

export function QuoteStaleBanner({ reason }: QuoteStaleBannerProps) {
  return (
    <Alert color="orange" title="数据可能滞后">
      <Text size="sm">{reason}</Text>
    </Alert>
  );
}
