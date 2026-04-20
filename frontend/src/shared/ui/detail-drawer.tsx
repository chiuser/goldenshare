import { Box, Divider, Drawer, Group, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";

type DetailDrawerSize = "sm" | "md" | "lg";

export const DETAIL_DRAWER_WIDTHS: Record<DetailDrawerSize, number> = {
  sm: 400,
  md: 600,
  lg: 800,
};

interface DetailDrawerProps {
  opened: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: DetailDrawerSize;
  withinPortal?: boolean;
}

export function DetailDrawer({
  opened,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  withinPortal,
}: DetailDrawerProps) {
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size={DETAIL_DRAWER_WIDTHS[size]}
      title={
        <Stack gap={2}>
          <Text fw={500} size="sm">
            {title}
          </Text>
          {description ? (
            <Text c="dimmed" size="xs">
              {description}
            </Text>
          ) : null}
        </Stack>
      }
      withinPortal={withinPortal}
      styles={{
        header: {
          alignItems: "flex-start",
          borderBottom: "1px solid var(--mantine-color-neutral-3)",
          paddingBlock: "var(--mantine-spacing-md)",
          paddingInline: "var(--mantine-spacing-lg)",
        },
        title: {
          flex: 1,
        },
        body: {
          display: "flex",
          flex: 1,
          flexDirection: "column",
          minHeight: 0,
          padding: 0,
        },
      }}
    >
      <Stack gap={0} h="100%">
        <Box px="lg" py="md" style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
          {children}
        </Box>
        {footer ? (
          <>
            <Divider />
            <Group
              justify="flex-end"
              px="lg"
              py="md"
              style={{ backgroundColor: "var(--mantine-color-neutral-0)" }}
            >
              {footer}
            </Group>
          </>
        ) : null}
      </Stack>
    </Drawer>
  );
}
