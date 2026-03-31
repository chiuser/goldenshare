import { Alert, Button, Paper, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { IconLock } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { useAuth } from "../features/auth/auth-context";
import { apiRequest } from "../shared/api/client";
import type { LoginResponse } from "../shared/api/types";


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
      setToken(data.token);
      await navigate({ to: "/ops/overview" });
    },
    onError: (error) => {
      setErrorText(error instanceof Error ? error.message : "登录失败，请稍后重试");
    },
  });

  return (
    <div
      className="app-gradient-shell"
      style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}
    >
      <Paper className="glass-card" radius="xl" p={36} miw={360} maw={460}>
        <Stack gap="xl">
          <Stack gap={6}>
            <Text c="dimmed" fw={700} size="sm" tt="uppercase">
              财势乾坤前端平台
            </Text>
            <Title order={1}>登录前端应用</Title>
            <Text c="dimmed" size="sm">
              这一版先为运维系统和后续行情工作台建立统一前端基础。
            </Text>
          </Stack>

          {errorText ? (
            <Alert color="red" title="登录失败">
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
            radius="xl"
            loading={loginMutation.isPending}
            onClick={() => loginMutation.mutate()}
          >
            进入应用
          </Button>
        </Stack>
      </Paper>
    </div>
  );
}
