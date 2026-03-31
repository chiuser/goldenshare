import { Group } from "@mantine/core";
import type { ReactNode } from "react";

import { HelpTip } from "./help-tip";


interface LabelWithHelpProps {
  label: ReactNode;
  help?: string;
  maxWidth?: number;
  iconSize?: number;
  gap?: number;
}

export function LabelWithHelp({
  label,
  help,
  maxWidth = 280,
  iconSize = 16,
  gap = 6,
}: LabelWithHelpProps) {
  return (
    <Group gap={gap} align="center" wrap="nowrap">
      {label}
      {help ? <HelpTip label={help} maxWidth={maxWidth} size={iconSize} /> : null}
    </Group>
  );
}
