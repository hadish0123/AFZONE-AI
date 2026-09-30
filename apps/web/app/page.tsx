"use client";

import {
  ArrowLeft,
  Eye,
  EyeOff,
  Gauge,
  KeyRound,
  LockKeyhole,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import PrimePanelV2 from "../components/PrimePanelV2";
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
  const [showPassword, setShowPassword] = useState(false);
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

  return (
    <main className="primeLoginPage" dir="rtl">
      <div className="primeLoginOrb primeLoginOrbTop" />
      <div className="primeLoginOrb primeLoginOrbBottom" />
      <div className="primeLoginStars" />

      <section className="primeLoginOuter">
        <div className="primeLoginPanel">
          <div className="primeLoginBrand">
            <div className="primeLoginBrandText" dir="ltr">
              <strong>PRIME<span>VPN</span></strong>
              <small>Control Center</small>
            </div>
            <div className="primeLoginLogo">
              <ShieldCheck size={47} strokeWidth={2.25} />
            </div>
          </div>

          <div className="primeSecureTitle" dir="ltr">
            <i />
            <span>SECURE CONTROL PLANE</span>
            <i />
          </div>

          <div className="primeLoginIntro">
            <h1>ورود به <span>پنل مرکزی</span></h1>
            <p>مدیریت کاربران، فروش، کیف پول، مصرف، ربات‌ها و سرویس‌ها از یک داشبورد حرفه‌ای.</p>
          </div>

          <form onSubmit={submit} className="primeLoginForm">
            <label className="primeLoginField">
              <span className="primeLoginLabel">نام کاربری</span>
              <div className="primeLoginInput">
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  spellCheck={false}
                />
                <span className="primeFieldIcon primeFieldIconLeft"><UserRound size={23} /></span>
              </div>
            </label>

            <label className="primeLoginField">
              <span className="primeLoginLabel">رمز عبور</span>
              <div className="primeLoginInput">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                />
                <span className="primeFieldIcon primeFieldIconLeft"><LockKeyhole size={22} /></span>
                <button
                  type="button"
                  className="primePasswordToggle"
                  aria-label={showPassword ? "مخفی کردن رمز عبور" : "نمایش رمز عبور"}
                  onClick={() => setShowPassword((value) => !value)}
                >
                  {showPassword ? <Eye size={23} /> : <EyeOff size={23} />}
                </button>
              </div>
            </label>

            {otpRequired && (
              <label className="primeLoginField">
                <span className="primeLoginLabel">کد دو مرحله‌ای</span>
                <div className="primeLoginInput">
                  <input
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder="123456 یا Recovery Code"
                    value={otp}
                    onChange={(e) => setOtp(e.target.value)}
                  />
                  <span className="primeFieldIcon primeFieldIconLeft"><KeyRound size={22} /></span>
                </div>
              </label>
            )}

            {error && <div className="primeLoginError">{error}</div>}

            <button className="primeLoginButton" disabled={busy}>
              <span>{busy ? "در حال بررسی..." : otpRequired ? "تأیید و ورود" : "ورود امن"}</span>
              <i><ArrowLeft size={25} /></i>
            </button>
          </form>

          <div className="primeLoginSecurity" dir="ltr">
            <span>Rate limit</span>
            <b />
            <span>Secret encryption</span>
            <b />
            <span className="primeSession">Session <em>چرخشی</em></span>
            <ShieldCheck size={23} />
          </div>
        </div>
      </section>
    </main>
  );
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
    return (
      <main className="primeLoginPage">
        <div className="bootLoader">
          <Gauge size={34} />
          <strong>PRIMEVPN</strong>
          <span>در حال برقراری ارتباط امن...</span>
        </div>
      </main>
    );
  }

  if (!user) return <LoginScreen onLogin={setUser} />;
  return <PrimePanelV2 user={user} onSessionExpired={() => { clearSession(); setUser(null); }} />;
}
