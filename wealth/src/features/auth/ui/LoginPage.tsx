import { useEffect, useState, type FormEvent } from "react";

import coverUrl from "../../../assets/auth/cover.png";
import { useAuth } from "../model/AuthProvider";
import "./LoginPage.css";

interface LoginPageProps {
  redirectPath: string;
  onAuthenticated: (path: string) => void;
}

export function LoginPage({ redirectPath, onAuthenticated }: LoginPageProps) {
  const auth = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (auth.status === "authenticated") onAuthenticated(redirectPath);
  }, [auth.status, onAuthenticated, redirectPath]);

  useEffect(() => {
    if (!message) return undefined;
    const timer = window.setTimeout(() => setMessage(""), 2600);
    return () => window.clearTimeout(timer);
  }, [message]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedUsername = username.trim();
    const normalizedPassword = password.trim();
    if (!normalizedUsername || !normalizedPassword) {
      setMessage("请输入用户名和密码");
      return;
    }
    setSubmitting(true);
    try {
      await auth.login({
        username: normalizedUsername,
        password: normalizedPassword,
      });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "登录失败，请检查用户名或密码");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page" style={{ backgroundImage: `url(${coverUrl})` }} aria-label="财势乾坤行情系统登录页">
      <section className="login-cluster" aria-label="登录表单">
        <form className="login-form" onSubmit={handleSubmit}>
          <label className="csq-field">
            <span className="csq-label">用户名</span>
            <input
              className="csq-input"
              name="username"
              autoComplete="username"
              placeholder="请输入用户名"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>

          <label className="csq-field">
            <span className="csq-label">密码</span>
            <input
              className="csq-input"
              name="password"
              type="password"
              autoComplete="current-password"
              placeholder="请输入密码"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          <div className="button-row">
            <button className="csq-button" type="button" onClick={() => setMessage("注册入口暂未开放")}>
              注册
            </button>
            <button className="csq-button primary" type="submit" disabled={submitting}>
              {submitting ? "登录中" : "登录"}
            </button>
          </div>

          <div className={`login-message${message ? " show" : ""}`} role="status">
            {message}
          </div>
        </form>
      </section>

      <div className="corner-status">数据接入状态：登录保护已启用</div>
    </main>
  );
}
