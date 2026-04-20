import { Text, type TextProps } from "@mantine/core";

interface PriceTextProps extends Omit<TextProps, "children"> {
  value: number | string | null | undefined;
  digits?: number;
  placeholder?: string;
}

function formatPriceValue(value: number | string | null | undefined, digits: number, placeholder: string) {
  if (value === null || value === undefined || value === "") {
    return placeholder;
  }
  const parsed = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(parsed)) {
    return String(value);
  }
  return parsed.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function PriceText({
  value,
  digits = 2,
  placeholder = "—",
  span = true,
  ...props
}: PriceTextProps) {
  return (
    <Text className="price-text" span={span} {...props}>
      {formatPriceValue(value, digits, placeholder)}
    </Text>
  );
}
