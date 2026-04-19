import { Badge, Button, Card, MantineColorsTuple, NavLink, Paper, createTheme, rem } from "@mantine/core";

const brandScale: MantineColorsTuple = [
  "#EAF1FA",
  "#D8E6F6",
  "#BED4EC",
  "#8FB5DB",
  "#5C8FC5",
  "#1F5499",
  "#154173",
  "#0E325A",
  "#0A2547",
  "#061937",
];

const neutralScale: MantineColorsTuple = [
  "#FFFFFF",
  "#F7F8FA",
  "#F0F2F5",
  "#E5E7EB",
  "#D1D5DB",
  "#9CA3AF",
  "#6B7280",
  "#4B5563",
  "#1F2937",
  "#0F172A",
];

const upScale: MantineColorsTuple = [
  "#FDECEC",
  "#FADCDC",
  "#F4B9B9",
  "#EC8686",
  "#E04848",
  "#C73838",
  "#A82828",
  "#8A1F1F",
  "#6B1717",
  "#4D0F0F",
];

const downScale: MantineColorsTuple = [
  "#E6F4EE",
  "#D3ECDF",
  "#B1DEC8",
  "#78C3A0",
  "#1F9D6A",
  "#157E55",
  "#0B6E47",
  "#0A5A3B",
  "#08462E",
  "#053220",
];

const infoScale: MantineColorsTuple = [
  "#EAF1FA",
  "#D8E6F6",
  "#BFD4EC",
  "#8FB5DB",
  "#5C8FC5",
  "#1F5499",
  "#154173",
  "#0E325A",
  "#0A2547",
  "#061937",
];

const successScale: MantineColorsTuple = [
  "#E4F4EC",
  "#D2EBDF",
  "#B2DCC7",
  "#7EC09F",
  "#3AA472",
  "#0F8A5F",
  "#0D744F",
  "#0A5D3F",
  "#084830",
  "#063421",
];

const warningScale: MantineColorsTuple = [
  "#FBEFCC",
  "#F7E7B4",
  "#F0D58A",
  "#E6BF5A",
  "#D1A128",
  "#B07B00",
  "#946700",
  "#785300",
  "#5C4000",
  "#412D00",
];

const errorScale: MantineColorsTuple = [
  "#FBE9E9",
  "#F7D6D6",
  "#F0B4B4",
  "#E78A8A",
  "#D95D5D",
  "#B42626",
  "#951F1F",
  "#761818",
  "#581111",
  "#3B0A0A",
];

export const appTheme = createTheme({
  primaryColor: "brand",
  primaryShade: 5,
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", Roboto, "Helvetica Neue", Arial, sans-serif',
  fontFamilyMonospace:
    '"JetBrains Mono", "SF Mono", "Roboto Mono", Menlo, Consolas, monospace',
  fontSizes: {
    xs: rem(11),
    sm: rem(12),
    md: rem(13),
    lg: rem(14),
    xl: rem(16),
  },
  lineHeights: {
    xs: "1.4",
    sm: "1.4",
    md: "1.4",
    lg: "1.55",
    xl: "1.55",
  },
  headings: {
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", Roboto, "Helvetica Neue", Arial, sans-serif',
    fontWeight: "500",
    sizes: {
      h1: { fontSize: rem(28), lineHeight: "1.35" },
      h2: { fontSize: rem(22), lineHeight: "1.35" },
      h3: { fontSize: rem(18), lineHeight: "1.4" },
      h4: { fontSize: rem(16), lineHeight: "1.4" },
      h5: { fontSize: rem(14), lineHeight: "1.4" },
      h6: { fontSize: rem(13), lineHeight: "1.4" },
    },
  },
  spacing: {
    xs: rem(4),
    sm: rem(8),
    md: rem(12),
    lg: rem(16),
    xl: rem(20),
  },
  radius: {
    xs: rem(2),
    sm: rem(4),
    md: rem(6),
    lg: rem(8),
    xl: rem(12),
  },
  defaultRadius: "sm",
  shadows: {
    xs: "none",
    sm: "none",
    md: "0 4px 12px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.04)",
    lg: "0 12px 32px rgba(15, 23, 42, 0.10), 0 2px 6px rgba(15, 23, 42, 0.04)",
    xl: "0 12px 32px rgba(15, 23, 42, 0.10), 0 2px 6px rgba(15, 23, 42, 0.04)",
  },
  colors: {
    brand: brandScale,
    neutral: neutralScale,
    up: upScale,
    down: downScale,
    info: infoScale,
    success: successScale,
    warning: warningScale,
    error: errorScale,
  },
  components: {
    Button: Button.extend({
      defaultProps: {
        radius: "sm",
        size: "sm",
      },
      styles: {
        root: {
          height: rem(32),
          fontWeight: 500,
          letterSpacing: 0,
        },
      },
    }),
    Badge: Badge.extend({
      defaultProps: {
        radius: "sm",
        variant: "light",
      },
      styles: {
        root: {
          fontWeight: 500,
          textTransform: "none",
          letterSpacing: 0,
        },
      },
    }),
    NavLink: NavLink.extend({
      styles: (theme) => ({
        root: {
          borderRadius: theme.radius.md,
          fontWeight: 500,
        },
        label: {
          fontWeight: 500,
        },
        section: {
          color: theme.colors.brand[5],
        },
      }),
    }),
    Card: Card.extend({
      defaultProps: {
        radius: "md",
        withBorder: true,
      },
      styles: {
        root: {
          backgroundColor: themeColor("neutral", 0),
          border: `1px solid ${themeColor("neutral", 3)}`,
          boxShadow: "none",
        },
      },
    }),
    Paper: Paper.extend({
      styles: {
        root: {
          backgroundColor: themeColor("neutral", 0),
        },
      },
    }),
  },
});

function themeColor(scale: string, index: number) {
  return `var(--mantine-color-${scale}-${index})`;
}
