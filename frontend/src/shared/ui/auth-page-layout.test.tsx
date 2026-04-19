import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appTheme } from "../../app/theme";
import { AuthPageLayout } from "./auth-page-layout";

describe("AuthPageLayout", () => {
  it("renders heading, description, optional hero, and children", () => {
    render(
      <MantineProvider theme={appTheme}>
        <AuthPageLayout
          kicker="密码重置"
          title="忘记密码"
          description="输入用户名或邮箱后继续处理。"
          hero={<img src="/test-logo.png" alt="测试品牌" />}
        >
          <button type="button">继续</button>
        </AuthPageLayout>
      </MantineProvider>,
    );

    expect(screen.getByText("密码重置")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "忘记密码" })).toBeInTheDocument();
    expect(screen.getByText("输入用户名或邮箱后继续处理。")).toBeInTheDocument();
    expect(screen.getByAltText("测试品牌")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "继续" })).toBeInTheDocument();
  });
});
