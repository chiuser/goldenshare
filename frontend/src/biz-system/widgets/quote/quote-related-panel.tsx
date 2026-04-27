import { List, Paper, Stack, Text } from "@mantine/core";

import type { QuoteRelatedItemVM } from "../../entities/quote/quote-view-model";

interface QuoteRelatedPanelProps {
  items: QuoteRelatedItemVM[];
}

export function QuoteRelatedPanel({ items }: QuoteRelatedPanelProps) {
  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="xs">
        <Text fw={700}>相关信息</Text>
        <List spacing="xs" size="sm">
          {items.map((item) => (
            <List.Item key={`${item.type}-${item.title}-${item.value}`}>
              <Text span c="dimmed">
                {item.title}：
              </Text>
              <Text span>{item.value}</Text>
            </List.Item>
          ))}
        </List>
      </Stack>
    </Paper>
  );
}
