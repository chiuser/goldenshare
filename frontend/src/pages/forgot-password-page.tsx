import { Alert, Button, Stack, TextInput } from "@mantine/core";
import { IconKey, IconMailOpened } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { apiRequest } from "../shared/api/client";
import type { LookupAccountResponse } from "../shared/api/types";
import { AuthPageLayout } from "../shared/ui/auth-page-layout";


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
    <AuthPageLayout
      kicker="密码重置"
      title="忘记密码"
      description="输入用户名或邮箱。当前环境未接入邮件时，可使用调试令牌继续重置。"
    >
      <Stack gap="lg">
        {errorText ? (
          <Alert color="error" title="提交失败">
            {errorText}
          </Alert>
        ) : null}
        {messageText ? (
          <Alert color="info" title="已受理">
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
    </AuthPageLayout>
  );
}
