import { Alert, Button, Paper, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { IconKey, IconUserPlus } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { useAuth } from "../features/auth/auth-context";
import { apiRequest } from "../shared/api/client";
import type { CurrentUserResponse, LoginResponse, RegisterResponse } from "../shared/api/types";


export function RegisterPage() {
  const navigate = useNavigate();
  const { setToken } = useAuth();

  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [verifyToken, setVerifyToken] = useState("");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [tipText, setTipText] = useState<string | null>(null);

  const verifyMutation = useMutation({
    mutationFn: (token: string) =>
      apiRequest<LoginResponse>("/api/v1/auth/register/verify", {
        method: "POST",
        body: { token },
      }),
    onSuccess: async (data) => {
      setErrorText(null);
      setTipText("验证完成，已自动登录。");
      setToken(data.token, data.refresh_token);
      await navigate({ to: data.is_admin ? "/ops/v21/overview" : "/user/overview" });
    },
    onError: (error) => {
      setErrorText(error instanceof Error ? error.message : "验证失败，请稍后重试");
    },
  });

  const registerMutation = useMutation({
    mutationFn: () =>
      apiRequest<RegisterResponse>("/api/v1/auth/register", {
        method: "POST",
        body: {
          username,
          password,
          display_name: displayName || undefined,
          email: email || undefined,
          invite_code: inviteCode || undefined,
        },
      }),
    onSuccess: async (data) => {
      setErrorText(null);
      if (data.token) {
        setToken(data.token, data.refresh_token);
        const profile = await apiRequest<CurrentUserResponse>("/api/v1/auth/me", { token: data.token });
        await navigate({ to: profile.is_admin ? "/ops/v21/overview" : "/user/overview" });
        return;
      }
      if (data.verification_token_debug) {
        setVerifyToken(data.verification_token_debug);
        setTipText("注册成功。当前环境未接入邮件服务，请使用下方验证令牌完成激活。");
        return;
      }
      setTipText("注册成功，但当前环境未返回验证令牌。请联系管理员完成账号激活。");
    },
    onError: (error) => {
      setErrorText(error instanceof Error ? error.message : "注册失败，请稍后重试");
    },
  });

  const submitRegister = () => {
    if (!inviteCode.trim()) {
      setErrorText("邀请码不能为空");
      return;
    }
    if (password !== confirmPassword) {
      setErrorText("两次输入的密码不一致");
      return;
    }
    setErrorText(null);
    registerMutation.mutate();
  };

  const submitVerify = () => {
    if (!verifyToken.trim()) {
      setErrorText("请填写验证令牌");
      return;
    }
    setErrorText(null);
    verifyMutation.mutate(verifyToken.trim());
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
              邀请码注册
            </Text>
            <Title order={1}>创建账号</Title>
            <Text c="dimmed" size="sm">
              当前仅支持邀请码注册。未接入邮件服务时，可在本页使用调试验证令牌完成激活。
            </Text>
          </Stack>

          {errorText ? (
            <Alert color="red" title="提交失败">
              {errorText}
            </Alert>
          ) : null}
          {tipText ? (
            <Alert color="blue" title="提示">
              {tipText}
            </Alert>
          ) : null}

          <TextInput label="用户名" value={username} onChange={(event) => setUsername(event.currentTarget.value)} />
          <TextInput label="显示名称（可选）" value={displayName} onChange={(event) => setDisplayName(event.currentTarget.value)} />
          <TextInput label="邮箱（建议填写）" value={email} onChange={(event) => setEmail(event.currentTarget.value)} />
          <TextInput
            label="邀请码"
            value={inviteCode}
            onChange={(event) => setInviteCode(event.currentTarget.value)}
            leftSection={<IconKey size={16} />}
          />
          <PasswordInput label="密码" value={password} onChange={(event) => setPassword(event.currentTarget.value)} />
          <PasswordInput
            label="确认密码"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.currentTarget.value)}
          />
          <Button
            leftSection={<IconUserPlus size={16} />}
            loading={registerMutation.isPending}
            onClick={submitRegister}
          >
            提交注册
          </Button>

          <TextInput
            label="验证令牌（无邮件时使用）"
            value={verifyToken}
            onChange={(event) => setVerifyToken(event.currentTarget.value)}
          />
          <Button
            variant="light"
            loading={verifyMutation.isPending}
            onClick={submitVerify}
          >
            完成激活并登录
          </Button>

          <Button component={Link} to="/login" variant="subtle" size="sm">
            返回登录
          </Button>
        </Stack>
      </Paper>
    </div>
  );
}
