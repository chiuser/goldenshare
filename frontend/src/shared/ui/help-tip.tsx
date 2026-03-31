import { Text, Tooltip } from "@mantine/core";
import { IconHelpCircle } from "@tabler/icons-react";


interface HelpTipProps {
  label: string;
  maxWidth?: number;
  size?: number;
}

export function HelpTip({ label, maxWidth = 280, size = 16 }: HelpTipProps) {
  return (
    <Tooltip label={label} multiline maw={maxWidth} withArrow>
      <Text c="dimmed" component="span" style={{ display: "inline-flex", lineHeight: 0, cursor: "help" }}>
        <IconHelpCircle size={size} stroke={1.8} />
      </Text>
    </Tooltip>
  );
}
