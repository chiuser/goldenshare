import { Text, type TextProps } from "@mantine/core";

interface ChangeTextProps extends Omit<TextProps, "children"> {
  value: number | string | null | undefined;
  digits?: number;
  placeholder?: string;
  showSign?: boolean;
  suffix?: string;
}

function parseNumericValue(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(parsed)) {
    return null;
  }
  return parsed;
}

function resolveToneClass(parsed: number | null) {
  if (parsed === null || parsed === 0) {
    return "change-text--neutral";
  }
  return parsed > 0 ? "change-text--up" : "change-text--down";
}

function formatChangeValue(
  parsed: number | null,
  digits: number,
  placeholder: string,
  showSign: boolean,
  suffix: string,
) {
  if (parsed === null) {
    return placeholder;
  }
  const sign = showSign && parsed > 0 ? "+" : "";
  return `${sign}${parsed.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}${suffix}`;
}

export function ChangeText({
  value,
  digits = 2,
  placeholder = "—",
  showSign = true,
  span = true,
  suffix = "",
  ...props
}: ChangeTextProps) {
  const parsed = parseNumericValue(value);

  return (
    <Text className={`change-text ${resolveToneClass(parsed)}`} span={span} {...props}>
      {formatChangeValue(parsed, digits, placeholder, showSign, suffix)}
    </Text>
  );
}
