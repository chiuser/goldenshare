import { Code, Paper } from "@mantine/core";


export function JsonBlock({ value }: { value: unknown }) {
  return (
    <Paper withBorder radius="md" p="sm" bg="rgba(22, 30, 46, 0.95)">
      <Code
        block
        c="#d7ebff"
        style={{
          background: "transparent",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          lineHeight: 1.6,
        }}
      >
        {JSON.stringify(value ?? {}, null, 2)}
      </Code>
    </Paper>
  );
}
