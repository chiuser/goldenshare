import { Alert, Button, PasswordInput, Stack, TextInput } from "@mantine/core";
import { IconLock } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { useAuth } from "../features/auth/auth-context";
import { apiRequest } from "../shared/api/client";
import type { LoginResponse } from "../shared/api/types";
import { AuthPageLayout } from "../shared/ui/auth-page-layout";


export function ResetPasswordPage() {
  const navigate = useNavigate();
  const { setToken } = useAuth();
  const initialToken = useMemo(() => new URLSearchParams(window.location.search).get("token") || "", []);
  const [token, setResetToken] = useState(initialToken);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errorText, setErrorText] = useState<string | null>(null);

  const resetMutation = useMutation({
    mutationFn: () =>
      apiRequest<LoginResponse>("/api/v1/auth/reset-password", {
        method: "POST",
        body: { token, new_password: password },
      }),
    onSuccess: async (data) => {
      setErrorText(null);
      setToken(data.token, data.refresh_token);
      await navigate({ to: data.is_admin ? "/ops/v21/today" : "/user/overview" });
    },
    onError: (error) => {
      setErrorText(error instanceof Error ? error.message : "密码重置失败，请稍后重试");
    },
  });

  const submitReset = () => {
    if (!token.trim()) {
      setErrorText("请填写重置令牌");
      return;
    }
    if (!password) {
      setErrorText("请填写新密码");
      return;
    }
    if (password !== confirmPassword) {
      setErrorText("两次输入的密码不一致");
      return;
    }
    setErrorText(null);
    resetMutation.mutate();
  };

  return (
    <AuthPageLayout
      kicker="密码重置"
      title="设置新密码"
      description="请填写重置令牌与新密码，完成后会自动登录。"
    >
      <Stack gap="lg">
        {errorText ? (
          <Alert color="error" title="提交失败">
            {errorText}
          </Alert>
        ) : null}

        <TextInput
          label="重置令牌"
          value={token}
          onChange={(event) => setResetToken(event.currentTarget.value)}
        />
        <PasswordInput
          label="新密码"
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          leftSection={<IconLock size={16} />}
        />
        <PasswordInput
          label="确认新密码"
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.currentTarget.value)}
          leftSection={<IconLock size={16} />}
        />
        <Button loading={resetMutation.isPending} onClick={submitReset}>
          完成重置
        </Button>
        <Button component={Link} to="/login" variant="subtle" size="sm">
          返回登录
        </Button>
      </Stack>
    </AuthPageLayout>
  );
}
