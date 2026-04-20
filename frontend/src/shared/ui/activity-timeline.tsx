import { Group, Stack, Text, Timeline } from "@mantine/core";
import type { ReactNode } from "react";

interface ActivityTimelineItem {
  id: string | number;
  title: ReactNode;
  body?: ReactNode;
  meta?: ReactNode;
  bullet?: ReactNode;
  time?: ReactNode;
}

interface ActivityTimelineProps {
  active?: number;
  emptyState?: ReactNode;
  items: ActivityTimelineItem[];
}

export function ActivityTimeline({ active, emptyState, items }: ActivityTimelineProps) {
  if (!items.length) {
    return emptyState ?? null;
  }

  return (
    <Timeline active={active} bulletSize={18} className="activity-timeline" lineWidth={2}>
      {items.map((item) => (
        <Timeline.Item key={item.id} bullet={item.bullet}>
          <Stack className="activity-timeline__item" gap={6} pb="sm">
            <Group justify="space-between" align="flex-start" gap="md">
              <Text fw={700}>{item.title}</Text>
              {item.meta ? <div className="activity-timeline__meta">{item.meta}</div> : null}
            </Group>
            {item.time ? (
              <Text className="activity-timeline__time" size="sm">
                {item.time}
              </Text>
            ) : null}
            {item.body}
          </Stack>
        </Timeline.Item>
      ))}
    </Timeline>
  );
}
