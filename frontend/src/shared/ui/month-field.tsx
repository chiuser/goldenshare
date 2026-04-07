import { TextInput, type TextInputProps } from "@mantine/core";

type MonthFieldProps = Omit<TextInputProps, "type" | "value" | "onChange"> & {
  value: string;
  onChange: (value: string) => void;
};

export function MonthField({ value, onChange, ...props }: MonthFieldProps) {
  return (
    <TextInput
      {...props}
      type="month"
      value={value}
      onChange={(event) => onChange(event.currentTarget.value)}
    />
  );
}
