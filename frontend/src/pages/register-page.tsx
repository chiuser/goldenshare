import { Alert, Button, PasswordInput, Stack, TextInput } from "@mantine/core";
import { IconKey, IconUserPlus } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { useAuth } from "../features/auth/auth-context";
import { apiRequest } from "../shared/api/client";
import { ApiError } from "../shared/api/errors";
import type { CurrentUserResponse, LoginResponse, LookupAccountResponse, RegisterResponse } from "../shared/api/types";
import { AuthPageLayout } from "../shared/ui/auth-page-layout";


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
  const [showVerifySection, setShowVerifySection] = useState(false);

  const renderRegisterError = (error: unknown): string => {
    if (error instanceof ApiError) {
      if (error.code === "registration_closed") {
        return "当前后端未开启注册，请管理员在环境配置中设置 AUTH_REGISTER_MODE=invite_only。";
      }
      if (error.code === "invite_code_required") {
        return "请输入邀请码后再注册。";
      }
    }
    return error instanceof Error ? error.message : "注册失败，请稍后重试";
  };

  const resolveVerifyIdentifier = (): string => (email.trim() || username.trim());

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
      setShowVerifySection(true);
      setErrorText(error instanceof Error ? error.message : "验证失败，请稍后重试");
    },
  });

  const resendVerifyMutation = useMutation({
    mutationFn: () => {
      const usernameOrEmail = resolveVerifyIdentifier();
      if (!usernameOrEmail) {
        throw new Error("请先填写用户名或邮箱");
      }
      return apiRequest<LookupAccountResponse>("/api/v1/auth/register/resend-verification", {
        method: "POST",
        body: { username_or_email: usernameOrEmail },
      });
    },
    onSuccess: (data) => {
      setErrorText(null);
      if (data.token_debug) {
        setVerifyToken(data.token_debug);
        setTipText("已重新生成验证令牌，请点击“完成激活并登录”。");
        return;
      }
      setTipText("验证请求已提交。当前环境未返回调试令牌，请联系管理员或确认邮件服务。");
    },
    onError: (error) => {
      setErrorText(error instanceof Error ? error.message : "重新获取验证令牌失败");
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
      setShowVerifySection(false);
      if (data.token) {
        setToken(data.token, data.refresh_token);
        const profile = await apiRequest<CurrentUserResponse>("/api/v1/auth/me", { token: data.token });
        await navigate({ to: profile.is_admin ? "/ops/v21/overview" : "/user/overview" });
        return;
      }
      if (!data.requires_email_verification) {
        setTipText("注册成功，请返回登录。");
        return;
      }
      setShowVerifySection(true);
      if (data.verification_token_debug) {
        setVerifyToken(data.verification_token_debug);
        setTipText("注册成功，正在自动完成激活...");
        verifyMutation.mutate(data.verification_token_debug);
        return;
      }
      setTipText("注册成功。当前环境未返回验证令牌，请点击“重新获取验证令牌”或联系管理员。");
    },
    onError: (error) => {
      setErrorText(renderRegisterError(error));
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
    setTipText(null);
    setShowVerifySection(false);
    setVerifyToken("");
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
    <AuthPageLayout
      kicker="邀请码注册"
      title="创建账号"
      description="当前仅支持邀请码注册。未接入邮件服务时，可在本页使用调试验证令牌完成激活。"
    >
      <Stack gap="lg">
        {errorText ? (
          <Alert color="error" title="提交失败">
            {errorText}
          </Alert>
        ) : null}
        {tipText ? (
          <Alert color="info" title="提示">
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
        {showVerifySection ? (
          <>
            <TextInput
              label="验证令牌（无邮件时使用）"
              value={verifyToken}
              onChange={(event) => setVerifyToken(event.currentTarget.value)}
            />
            <Button
              variant="light"
              loading={verifyMutation.isPending}
              onClick={submitVerify}
              disabled={!verifyToken.trim()}
            >
              完成激活并登录
            </Button>
            <Button
              variant="subtle"
              loading={resendVerifyMutation.isPending}
              onClick={() => resendVerifyMutation.mutate()}
              disabled={!resolveVerifyIdentifier()}
            >
              重新获取验证令牌
            </Button>
          </>
        ) : null}

        <Button component={Link} to="/login" variant="subtle" size="sm">
          返回登录
        </Button>
      </Stack>
    </AuthPageLayout>
  );
}
