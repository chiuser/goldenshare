import { useEffect, useRef, useState, type FormEvent } from "react";

import backgroundUrl from "../../../assets/auth/wealth-world-login-bg-screen.png";
import { useAuth } from "../model/AuthProvider";
import { LoginBrand } from "./LoginBrand";
import "./login-fonts.css";
import "./LoginPage.css";

const LOGIN_FEEDBACK_DURATION_MS = 2600;
type Field = "username" | "password";
type Feedback = { id: number; message: string; invalidFields: Field[] };

interface LoginPageProps {
  redirectPath: string;
  onAuthenticated: (path: string) => void;
}

export function LoginPage({ redirectPath, onAuthenticated }: LoginPageProps) {
  const auth = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const feedbackId = useRef(0);
  const attemptId = useRef(0);
  const attempt = useRef<{ id: number; controller: AbortController } | null>(null);
  const submittingLock = useRef(false);
  const usernameInput = useRef<HTMLInputElement>(null);
  const passwordInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (auth.status === "authenticated") onAuthenticated(redirectPath);
  }, [auth.status, onAuthenticated, redirectPath]);

  useEffect(() => {
    if (!feedback) return;
    const timer = window.setTimeout(() => setFeedback(null), LOGIN_FEEDBACK_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [feedback]);

  useEffect(() => () => {
    const current = attempt.current;
    attempt.current = null;
    current?.controller.abort();
  }, []);

  function showFeedback(message: string, invalidFields: Field[] = []) {
    setFeedback({ id: ++feedbackId.current, message, invalidFields });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submittingLock.current) return;
    const body = { username: username.trim(), password: password.trim() };
    const invalidFields = (["username", "password"] as const).filter((field) => !body[field]);
    if (invalidFields.length) {
      showFeedback("请输入用户名和密码", invalidFields);
      (invalidFields[0] === "username" ? usernameInput : passwordInput).current?.focus();
      return;
    }
    submittingLock.current = true;
    const current = { id: ++attemptId.current, controller: new AbortController() };
    attempt.current = current;
    setSubmitting(true);
    setFeedback(null);
    try {
      await auth.login(body, { signal: current.controller.signal });
    } catch (error) {
      if (attempt.current !== current) return;
      if (error instanceof DOMException && error.name === "AbortError") return;
      showFeedback(error instanceof DOMException && error.name === "TimeoutError"
        ? "登录超时，请重试"
        : error instanceof Error ? error.message : "登录失败，请检查用户名或密码");
    } finally {
      if (attempt.current === current) {
        attempt.current = null;
        submittingLock.current = false;
        setSubmitting(false);
      }
    }
  }

  return (
    <main className="login-page" aria-label="财势天下登录页">
      <div className="login-background" style={{ backgroundImage: `url(${backgroundUrl})` }} aria-hidden="true" />
      <section className="login-cluster" aria-label="登录表单">
        <LoginBrand />
        <form className="login-form" onSubmit={handleSubmit} noValidate aria-busy={submitting}
          aria-describedby={feedback && !feedback.invalidFields.length ? "login-feedback" : undefined}>
          <div className="login-field">
            <label className="login-visually-hidden" htmlFor="login-username">用户名</label>
            <input id="login-username" ref={usernameInput} name="username" autoComplete="username"
              placeholder="请输入用户名" value={username} onChange={(event) => setUsername(event.target.value)}
              aria-invalid={feedback?.invalidFields.includes("username") || undefined}
              aria-describedby={feedback?.invalidFields.includes("username") ? "login-feedback" : undefined} />
          </div>
          <div className="login-field">
            <label className="login-visually-hidden" htmlFor="login-password">密码</label>
            <input id="login-password" ref={passwordInput} name="password" type="password" autoComplete="current-password"
              placeholder="请输入密码" value={password} onChange={(event) => setPassword(event.target.value)}
              aria-invalid={feedback?.invalidFields.includes("password") || undefined}
              aria-describedby={feedback?.invalidFields.includes("password") ? "login-feedback" : undefined} />
          </div>
          <div className="login-action">
            <button type="submit" disabled={submitting} data-loading={submitting || undefined}>
              {submitting ? "登录中…" : "登录"}
            </button>
          </div>
          <div id="login-feedback" className="login-feedback" role="status" aria-live="polite">
            {feedback && <span key={feedback.id}>{feedback.message}</span>}
          </div>
        </form>
      </section>
    </main>
  );
}
