import { Alert, Button, Paper, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { IconLock } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { useAuth } from "../features/auth/auth-context";
import { apiRequest } from "../shared/api/client";
import type { LoginResponse } from "../shared/api/types";


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
      await navigate({ to: data.is_admin ? "/ops/v21/overview" : "/user/overview" });
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
    <div
      className="app-gradient-shell"
      style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}
    >
      <Paper className="glass-card" radius="xl" p={36} miw={360} maw={500}>
        <Stack gap="lg">
          <Stack gap={6}>
            <Text c="dimmed" fw={700} size="sm" tt="uppercase">
              密码重置
            </Text>
            <Title order={1}>设置新密码</Title>
            <Text c="dimmed" size="sm">
              请填写重置令牌与新密码，完成后会自动登录。
            </Text>
          </Stack>

          {errorText ? (
            <Alert color="red" title="提交失败">
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
      </Paper>
    </div>
  );
}
