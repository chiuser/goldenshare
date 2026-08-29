import { Checkbox, Group, Stack, Text } from "@mantine/core";

type OpsEnumMultiSelectProps = {
  label: string;
  description?: string;
  options: string[];
  optionLabels?: Record<string, string>;
  value: string[];
  onChange: (value: string[]) => void;
  selectAllEnabled?: boolean;
  layout?: "row" | "column";
};

function normalizedSelection(value: string[], options: string[]) {
  const allowed = new Set(options);
  return Array.from(new Set(value.filter((item) => allowed.has(item))));
}

export function OpsEnumMultiSelect({
  label,
  description,
  options,
  optionLabels = {},
  value,
  onChange,
  selectAllEnabled = false,
  layout = "column",
}: OpsEnumMultiSelectProps) {
  const selected = normalizedSelection(value, options);
  const selectedSet = new Set(selected);
  const allSelected = options.length > 0
    && selected.length === options.length
    && options.every((option) => selectedSet.has(option));
  const OptionLayout = layout === "row" ? Group : Stack;

  return (
    <Stack gap={6}>
      <div>
        <Text fw={500} size="sm">{label}</Text>
        {description ? <Text c="dimmed" size="xs">{description}</Text> : null}
      </div>
      {selectAllEnabled ? (
        <Checkbox
          checked={allSelected}
          label="全部"
          onChange={(event) => onChange(event.currentTarget.checked ? [...options] : [])}
        />
      ) : null}
      <Checkbox.Group value={selected} onChange={onChange}>
        <OptionLayout gap={layout === "row" ? "lg" : 6}>
          {options.map((option) => (
            <Checkbox
              key={option}
              value={option}
              label={optionLabels[option] || option}
              disabled={selectAllEnabled && allSelected}
            />
          ))}
        </OptionLayout>
      </Checkbox.Group>
    </Stack>
  );
}
