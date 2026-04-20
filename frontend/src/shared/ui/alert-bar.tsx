import { Alert, Box, Text } from "@mantine/core";
import type { ReactNode } from "react";
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconInfoCircle,
  IconX,
} from "@tabler/icons-react";

type AlertTone = "neutral" | "info" | "success" | "warning" | "error";

const ICON_MAP: Record<AlertTone, ReactNode> = {
  neutral: <IconInfoCircle size={16} stroke={1.75} />,
  info: <IconInfoCircle size={16} stroke={1.75} />,
  success: <IconCircleCheck size={16} stroke={1.75} />,
  warning: <IconAlertTriangle size={16} stroke={1.75} />,
  error: <IconX size={16} stroke={1.75} />,
};

interface AlertBarProps {
  tone?: AlertTone;
  title: string;
  children?: ReactNode;
}

export function AlertBar({
  tone = "info",
  title,
  children,
}: AlertBarProps) {
  return (
    <Alert
      className="alert-bar"
      color={tone}
      data-tone={tone}
      icon={ICON_MAP[tone]}
      radius="md"
      title={title}
      variant="light"
      styles={(theme) => ({
        root: {
          backgroundColor: theme.colors[tone][0],
          border: `1px solid ${theme.colors[tone][2]}`,
          borderLeft: `3px solid ${theme.colors[tone][5]}`,
          boxShadow: "none",
          paddingBlock: theme.spacing.sm,
          paddingInline: theme.spacing.md,
        },
        icon: {
          color: theme.colors[tone][5],
          marginTop: 2,
        },
        title: {
          color: theme.colors.neutral[8],
          fontSize: theme.fontSizes.sm,
          fontWeight: 500,
          lineHeight: theme.lineHeights.sm,
          marginBottom: children ? theme.spacing.xs : 0,
        },
        message: {
          color: theme.colors.neutral[7],
          fontSize: theme.fontSizes.sm,
          lineHeight: theme.lineHeights.lg,
        },
      })}
    >
      {typeof children === "string" ? <Text size="sm">{children}</Text> : children}
    </Alert>
  );
}

export function AlertBarNote({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <Box component="span" c="dimmed" display="block" fz="xs" mt={6}>
      {children}
    </Box>
  );
}
