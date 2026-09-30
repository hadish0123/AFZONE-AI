"use client";

import { Gauge, ShieldCheck } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import PrimePanel from "../components/PrimePanel";
import {
  ApiError,
  authApi,
  clearSession,
  login,
  SessionUser,
  storedSession,
} from "../lib/api";

function LoginScreen({ onLogin }: { onLogin: (user: SessionUser) => void }) {
  const [username, setUsername] = useState("PrimeOwner");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [otpRequired, setOtpRequired] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await login(username.trim(), password, otpRequired ? otp : undefined);
      onLogin(result.user);
    } catch (err) {
      if (err instanceof ApiError && err.status === 428 && err.detail === "otp_required") {
        setOtpRequired(true);
        setError("کد Authenticator را وارد کنید.");
      } else if (err instanceof ApiError && err.detail === "invalid_otp") {
        setOtpRequired(true);
        setError("کد دو مرحله‌ای صحیح نیست.");
      } else {
        setError(err instanceof Error ? err.message : "ورود ناموفق بود");
      }
    } finally {
      setBusy(false);
    }
  }

  return <main className="loginPage">
    <section className="loginCard glass">
      <div className="loginGlow"/>
      <div className="loginBrand"><div className="brandMark"><Gauge size={28}/></div><div><strong>PRIMEVPN</strong><span>Control Center</span></div></div>
      <div className="loginCopy">
        <p className="eyebrow">SECURE CONTROL PLANE</p>
        <h1>ورود به پنل مرکزی</h1>
        <p>مدیریت نمایندگان، کیف پول، فروش، مصرف واقعی، ربات‌ها و PasarGuard از یک نقطه.</p>
      </div>
      <form onSubmit={submit} className="loginForm">
        <label>نام کاربری<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"/></label>
        <label>رمز عبور<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"/></label>
        {otpRequired && <label>کد دو مرحله‌ای<input inputMode="numeric" autoComplete="one-time-code" placeholder="123456 یا Recovery Code" value={otp} onChange={(e) => setOtp(e.target.value)}/></label>}
        {error && <div className="formError">{error}</div>}
        <button className="primary loginButton" disabled={busy}>{busy ? "در حال بررسی..." : otpRequired ? "تأیید و ورود" : "ورود امن"}</button>
      </form>
      <div className="loginFoot"><ShieldCheck size={16}/> Session چرخشی · Rate limit · Secret encryption</div>
    </section>
  </main>;
}

export default function Home() {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [booting, setBooting] = useState(true);

  useEffect(() => {
    const session = storedSession();
    if (!session) {
      setBooting(false);
      return;
    }
    authApi<SessionUser>("/api/v1/me")
      .then((me) => setUser(me))
      .catch(() => {
        clearSession();
        setUser(null);
      })
      .finally(() => setBooting(false));
  }, []);

  if (booting) {
    return <main className="loginPage"><div className="bootLoader"><Gauge size={34}/><strong>PRIMEVPN</strong><span>در حال برقراری ارتباط امن...</span></div></main>;
  }

  if (!user) return <LoginScreen onLogin={setUser}/>;
  return <PrimePanel user={user} onSessionExpired={() => { clearSession(); setUser(null); }}/>;
}
