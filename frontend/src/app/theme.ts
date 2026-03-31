import { createTheme } from "@mantine/core";


export const appTheme = createTheme({
  primaryColor: "cyan",
  primaryShade: 7,
  fontFamily: '"IBM Plex Sans", "PingFang SC", "Microsoft YaHei", sans-serif',
  headings: {
    fontFamily: '"IBM Plex Sans", "PingFang SC", "Microsoft YaHei", sans-serif',
  },
  defaultRadius: "md",
  colors: {
    cyan: [
      "#e5fbfe",
      "#cdf5fa",
      "#9de8f1",
      "#67d9e6",
      "#3ecddd",
      "#25c5d7",
      "#12c0d4",
      "#00a9bb",
      "#0097a8",
      "#008392",
    ],
    sand: [
      "#fbf8f1",
      "#f4ede0",
      "#e8d7b7",
      "#ddc08a",
      "#d3ac62",
      "#cc9f49",
      "#c99a3b",
      "#b0862d",
      "#9d7723",
      "#886619",
    ],
  },
});
