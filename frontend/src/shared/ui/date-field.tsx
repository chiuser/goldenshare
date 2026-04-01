import { TextInput, type TextInputProps } from "@mantine/core";

type DateFieldProps = Omit<TextInputProps, "type" | "value" | "onChange"> & {
  value: string;
  onChange: (value: string) => void;
};

export function DateField({ value, onChange, ...props }: DateFieldProps) {
  return (
    <TextInput
      {...props}
      type="date"
      value={value}
      onChange={(event) => onChange(event.currentTarget.value)}
    />
  );
}
