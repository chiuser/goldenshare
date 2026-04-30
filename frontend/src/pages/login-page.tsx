import { Alert, Button, PasswordInput, Stack, TextInput } from "@mantine/core";
import { IconLock } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { useAuth } from "../features/auth/auth-context";
import { apiRequest } from "../shared/api/client";
import { ApiError } from "../shared/api/errors";
import type { LoginResponse } from "../shared/api/types";
import { AuthPageLayout } from "../shared/ui/auth-page-layout";


export function LoginPage() {
  const navigate = useNavigate();
  const { setToken } = useAuth();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [errorText, setErrorText] = useState<string | null>(null);

  const loginMutation = useMutation({
    mutationFn: () =>
      apiRequest<LoginResponse>("/api/v1/auth/login", {
        method: "POST",
        body: { username, password },
      }),
    onSuccess: async (data) => {
      setErrorText(null);
      setToken(data.token, data.refresh_token);
      await navigate({ to: data.is_admin ? "/ops/v21/today" : "/user/overview" });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "email_verification_required") {
        setErrorText("账号尚未完成验证，请先完成注册验证。");
        return;
      }
      setErrorText(error instanceof Error ? error.message : "登录失败，请稍后重试");
    },
  });

  return (
    <AuthPageLayout
      kicker="财势乾坤前端平台"
      title="登录前端应用"
      description="这一版先为运维系统和后续行情工作台建立统一前端基础。"
      maxWidth={460}
      hero={
        <img
          src="/app/brand/logo-full.png"
          alt="财势乾坤"
          className="login-brand-logo"
        />
      }
    >
      <Stack gap="xl">
        {errorText ? (
          <Alert color="error" title="登录失败">
            {errorText}
          </Alert>
        ) : null}

        <TextInput
          label="用户名"
          value={username}
          onChange={(event) => setUsername(event.currentTarget.value)}
          autoComplete="username"
        />
        <PasswordInput
          label="密码"
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          autoComplete="current-password"
        />
        <Button
          leftSection={<IconLock size={16} />}
          size="md"
          loading={loginMutation.isPending}
          onClick={() => loginMutation.mutate()}
        >
          进入应用
        </Button>
        <Button component={Link} to="/register" variant="subtle" size="sm">
          使用邀请码注册
        </Button>
        <Button component={Link} to="/forgot-password" variant="subtle" size="sm">
          忘记密码
        </Button>
      </Stack>
    </AuthPageLayout>
  );
}
