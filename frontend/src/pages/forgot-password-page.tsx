import { Alert, Button, Paper, Stack, Text, TextInput, Title } from "@mantine/core";
import { IconKey, IconMailOpened } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { apiRequest } from "../shared/api/client";
import type { LookupAccountResponse } from "../shared/api/types";


export function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [usernameOrEmail, setUsernameOrEmail] = useState("");
  const [tokenDebug, setTokenDebug] = useState("");
  const [messageText, setMessageText] = useState<string | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);

  const forgotMutation = useMutation({
    mutationFn: () =>
      apiRequest<LookupAccountResponse>("/api/v1/auth/forgot-password", {
        method: "POST",
        body: { username_or_email: usernameOrEmail },
      }),
    onSuccess: (data) => {
      setErrorText(null);
      setMessageText(data.message || "如果账号存在，系统已处理重置请求。");
      setTokenDebug(data.token_debug || "");
    },
    onError: (error) => {
      setErrorText(error instanceof Error ? error.message : "提交失败，请稍后重试");
    },
  });

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
            <Title order={1}>忘记密码</Title>
            <Text c="dimmed" size="sm">
              输入用户名或邮箱。当前环境未接入邮件时，可使用调试令牌继续重置。
            </Text>
          </Stack>

          {errorText ? (
            <Alert color="red" title="提交失败">
              {errorText}
            </Alert>
          ) : null}
          {messageText ? (
            <Alert color="blue" title="已受理">
              {messageText}
            </Alert>
          ) : null}

          <TextInput
            label="用户名或邮箱"
            value={usernameOrEmail}
            onChange={(event) => setUsernameOrEmail(event.currentTarget.value)}
            leftSection={<IconMailOpened size={16} />}
          />
          <Button loading={forgotMutation.isPending} onClick={() => forgotMutation.mutate()}>
            提交重置请求
          </Button>

          <TextInput
            label="重置令牌（无邮件时使用）"
            value={tokenDebug}
            onChange={(event) => setTokenDebug(event.currentTarget.value)}
            leftSection={<IconKey size={16} />}
          />
          <Button
            variant="light"
            onClick={async () => {
              await navigate({ to: `/reset-password?token=${encodeURIComponent(tokenDebug)}` });
            }}
            disabled={!tokenDebug.trim()}
          >
            进入重置页面
          </Button>

          <Button component={Link} to="/login" variant="subtle" size="sm">
            返回登录
          </Button>
        </Stack>
      </Paper>
    </div>
  );
}
