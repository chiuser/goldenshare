import { Badge, Button, Card, NavLink, createTheme } from "@mantine/core";

const brandScale = [
  "#f72585",
  "#b5179e",
  "#7209b7",
  "#560bad",
  "#480ca8",
  "#3a0ca3",
  "#3f37c9",
  "#4361ee",
  "#4895ef",
  "#4cc9f0",
] as const;

export const appTheme = createTheme({
  primaryColor: "brand",
  primaryShade: 7,
  fontFamily: '"IBM Plex Sans", "PingFang SC", "Microsoft YaHei", sans-serif',
  headings: {
    fontFamily: '"IBM Plex Sans", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontWeight: "700",
  },
  defaultRadius: "md",
  colors: {
    brand: brandScale,
    ink: [
      "#f4f6ff",
      "#e5e9fb",
      "#c6cde8",
      "#a6aed5",
      "#8c95c3",
      "#7a83b8",
      "#707caf",
      "#5d679a",
      "#525b8a",
      "#454c75",
    ],
  },
  components: {
    Button: Button.extend({
      defaultProps: {
        radius: "xl",
      },
    }),
    Badge: Badge.extend({
      defaultProps: {
        radius: "xl",
      },
    }),
    NavLink: NavLink.extend({
      styles: (theme) => ({
        root: {
          borderRadius: theme.radius.lg,
          fontWeight: 600,
        },
        section: {
          color: theme.colors.brand[7],
        },
      }),
    }),
    Card: Card.extend({
      styles: {
        root: {
          border: "1px solid rgba(63, 55, 201, 0.08)",
          boxShadow: "0 18px 40px rgba(58, 12, 163, 0.08)",
        },
      },
    }),
  },
});
