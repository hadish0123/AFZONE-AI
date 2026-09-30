"use client";

import {
  Activity,
  Bot,
  Boxes,
  CircleDollarSign,
  Gauge,
  LayoutDashboard,
  LogOut,
  RefreshCw,
  Server,
  Settings,
  ShieldCheck,
  Users,
  WalletCards,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, login, SessionUser } from "../lib/api";

type AdminRow = {
  id: string;
  username: string;
  display_name?: string | null;
  status: string;
  wallet_balance_toman: string;
};

type ClientRow = {
  id: string;
  username: string;
  status: string;
  quota_bytes: number | null;
  lifetime_usage_bytes: number;
};

type PlanRow = {
  id: string;
  name: string;
  enabled?: boolean;
  base_price_per_gib_toman?: string;
  retail_price_per_gib_toman?: string;
};

type PaymentRow = {
  id: string;
  status: string;
  amount_toman: string;
  purpose?: string | null;
};

type ConnectionRow = {
  id: string;
  name: string;
  enabled: boolean;
  last_error?: string | null;
};

const nav = [
  [LayoutDashboard, "داشبورد"],
  [Users, "نمایندگان"],
  [ShieldCheck, "کلاینت‌ها"],
  [Boxes, "پلن‌ها و گروه‌ها"],
  [WalletCards, "کیف پول"],
  [CircleDollarSign, "فروش و پرداخت"],
  [Bot, "ربات‌های فروش"],
  [Server, "PasarGuard"],
  [Activity, "گزارش مصرف"],
  [Settings, "تنظیمات"],
] as const;

const fmtMoney = (value: string | number | undefined) =>
  new Intl.NumberFormat("fa-IR").format(Number(value || 0)) + " تومان";

const fmtGiB = (bytes: number | undefined) =>
  (Number(bytes || 0) / 1024 ** 3).toLocaleString("fa-IR", { maximumFractionDigits: 2 }) + " GiB";

function LoginScreen({ onLogin }: { onLogin: (token: string, user: SessionUser) => void }) {
  const [username, setUsername] = useState("PrimeOwner");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await login(username.trim(), password);
      onLogin(result.access_token, result.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ورود ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="loginPage">
      <section className="loginCard glass">
        <div className="loginGlow" />
        <div className="loginBrand">
          <div className="brandMark"><Gauge size={28} /></div>
          <div><strong>PRIMEVPN</strong><span>Control Center</span></div>
        </div>
        <div className="loginCopy">
          <p className="eyebrow">SECURE CONTROL PLANE</p>
          <h1>ورود به پنل مرکزی</h1>
          <p>مدیریت نمایندگان، کیف پول، مصرف واقعی، فروش و PasarGuard از یک نقطه.</p>
        </div>
        <form onSubmit={submit} className="loginForm">
          <label>نام کاربری<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
          <label>رمز عبور<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
          {error && <div className="formError">{error}</div>}
          <button className="primary loginButton" disabled={busy}>{busy ? "در حال بررسی..." : "ورود امن"}</button>
        </form>
        <div className="loginFoot"><ShieldCheck size={16} /> ارتباط رمزگذاری‌شده · Secretها در رابط نمایش داده نمی‌شوند</div>
      </section>
    </main>
  );
}

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [me, setMe] = useState<SessionUser | null>(null);
  const [admins, setAdmins] = useState<AdminRow[]>([]);
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [payments, setPayments] = useState<PaymentRow[]>([]);
  const [connections, setConnections] = useState<ConnectionRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeNav, setActiveNav] = useState("داشبورد");
  const [error, setError] = useState("");

  useEffect(() => {
    const stored = localStorage.getItem("primevpn_token");
    if (!stored) return;
    setToken(stored);
    api<SessionUser>("/api/v1/me", {}, stored)
      .then(setMe)
      .catch(() => {
        localStorage.removeItem("primevpn_token");
        setToken(null);
      });
  }, []);

  async function loadDashboard(currentToken = token, currentUser = me) {
    if (!currentToken || !currentUser) return;
    setLoading(true);
    setError("");
    try {
      const common = await Promise.all([
        api<ClientRow[]>("/api/v1/clients", {}, currentToken),
        api<PlanRow[]>("/api/v1/plans", {}, currentToken),
        api<PaymentRow[]>("/api/v1/payments", {}, currentToken),
        api<SessionUser>("/api/v1/me", {}, currentToken),
      ]);
      setClients(common[0]);
      setPlans(common[1]);
      setPayments(common[2]);
      setMe(common[3]);

      if (currentUser.role === "owner") {
        const ownerData = await Promise.all([
          api<AdminRow[]>("/api/v1/admins", {}, currentToken),
          api<ConnectionRow[]>("/api/v1/connections", {}, currentToken),
        ]);
        setAdmins(ownerData[0]);
        setConnections(ownerData[1]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا در دریافت اطلاعات");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (token && me) loadDashboard(token, me);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, me?.id]);

  function completeLogin(newToken: string, user: SessionUser) {
    localStorage.setItem("primevpn_token", newToken);
    setToken(newToken);
    setMe(user);
  }

  function logout() {
    localStorage.removeItem("primevpn_token");
    setToken(null);
    setMe(null);
    setAdmins([]);
    setClients([]);
    setPlans([]);
    setPayments([]);
    setConnections([]);
  }

  const activeClients = useMemo(() => clients.filter((x) => x.status === "active").length, [clients]);
  const totalUsage = useMemo(() => clients.reduce((sum, item) => sum + Number(item.lifetime_usage_bytes || 0), 0), [clients]);
  const pendingPayments = useMemo(() => payments.filter((x) => x.status === "awaiting_review").length, [payments]);

  if (!token || !me) return <LoginScreen onLogin={completeLogin} />;

  const cards = me.role === "owner"
    ? [
        ["نمایندگان", String(admins.length), "Owner"],
        ["کلاینت‌های فعال", String(activeClients), String(clients.length) + " کل"],
        ["مصرف ثبت‌شده", fmtGiB(totalUsage), "Lifetime"],
        ["پرداخت منتظر", String(pendingPayments), "Review"],
      ]
    : [
        ["موجودی کیف پول", fmtMoney(me.wallet_balance_toman), "Live"],
        ["کلاینت‌های فعال", String(activeClients), String(clients.length) + " کل"],
        ["مصرف ثبت‌شده", fmtGiB(totalUsage), "Lifetime"],
        ["پرداخت‌های من", String(payments.length), String(pendingPayments) + " منتظر"],
      ];

  return (
    <main className="shell">
      <aside className="sidebar glass">
        <div className="brand">
          <div className="brandMark"><Gauge size={25} /></div>
          <div><strong>PRIMEVPN</strong><span>{me.role === "owner" ? "Owner Console" : "Admin Console"}</span></div>
        </div>

        <nav>
          {nav.filter(([, label]) => me.role === "owner" || label !== "نمایندگان").map(([Icon, label]) => (
            <button
              className={activeNav === label ? "navItem active" : "navItem"}
              key={label}
              onClick={() => setActiveNav(label)}
            >
              <Icon size={19}/><span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="ownerCard">
          <div className="avatar">{(me.display_name || me.username).slice(0, 1).toUpperCase()}</div>
          <div><strong>{me.display_name || me.username}</strong><span>{me.role}</span></div>
          <button className="iconButton" onClick={logout} title="خروج"><LogOut size={16}/></button>
        </div>
      </aside>

      <section className="workspace">
        <header>
          <div>
            <p className="eyebrow">PRIME NETWORK · LIVE</p>
            <h1>{activeNav}</h1>
            <p className="muted">{me.role === "owner" ? "مرکز کنترل مالک PRIMEVPN" : "پنل فروش و مدیریت سرویس نماینده"}</p>
          </div>
          <div className="headerActions">
            <button className="ghost" onClick={() => loadDashboard()} disabled={loading}><RefreshCw size={15}/> {loading ? "در حال بروزرسانی" : "همگام‌سازی"}</button>
            {me.role === "owner" && <button className="primary">+ نماینده جدید</button>}
          </div>
        </header>

        {error && <div className="pageError">{error}</div>}

        <section className="metrics">
          {cards.map(([title, value, meta], index) => (
            <article className={"metric metric" + index} key={title}>
              <div className="metricTop"><span>{title}</span><span className="pill">{meta}</span></div>
              <strong>{value}</strong>
              <div className="spark"><i/><i/><i/><i/><i/><i/><i/></div>
            </article>
          ))}
        </section>

        <section className="grid">
          <article className="panel wide">
            <div className="panelHead">
              <div><h2>مصرف و Billing</h2><p>کسر کیف پول فقط بر اساس Lifetime Usage واقعی PasarGuard</p></div>
              <span className="live"><i/> LIVE</span>
            </div>
            <div className="usageHero">
              <div><span>مصرف کل ثبت‌شده</span><strong>{fmtGiB(totalUsage)}</strong></div>
              <div><span>کلاینت‌های فعال</span><strong>{activeClients.toLocaleString("fa-IR")}</strong></div>
              <div><span>پرداخت منتظر بررسی</span><strong>{pendingPayments.toLocaleString("fa-IR")}</strong></div>
            </div>
            <div className="chart">
              {[40,63,48,76,58,84,71,92,68,88,75,96].map((height, i) => (
                <div className="bar" key={i}><span style={{height: height + "%"}}/></div>
              ))}
            </div>
          </article>

          <article className="panel">
            <div className="panelHead"><div><h2>وضعیت زیرساخت</h2><p>سرویس‌های متصل</p></div></div>
            {[
              ["API PRIMEVPN", true],
              ["Billing Worker", true],
              ["PostgreSQL / Redis", true],
              ["PasarGuard", connections.length > 0],
            ].map(([name, ok]) => (
              <div className="statusRow" key={String(name)}>
                <span><i className={ok ? "dot" : "dot amber"}/>{name}</span>
                <b>{ok ? "آماده" : "منتظر اتصال"}</b>
              </div>
            ))}
          </article>

          <article className="panel">
            <div className="panelHead"><div><h2>پلن‌ها</h2><p>پلن‌های قابل استفاده</p></div><span className="pill">{plans.length.toLocaleString("fa-IR")}</span></div>
            <div className="compactList">
              {plans.slice(0, 5).map((plan) => (
                <div key={plan.id}>
                  <strong>{plan.name}</strong>
                  <span>{fmtMoney(plan.retail_price_per_gib_toman || plan.base_price_per_gib_toman)} / GiB</span>
                </div>
              ))}
              {!plans.length && <div className="emptyMini">هنوز پلنی تعریف نشده.</div>}
            </div>
          </article>

          <article className="panel wide">
            <div className="panelHead"><div><h2>آخرین کلاینت‌ها</h2><p>Mirror عملیاتی PasarGuard</p></div></div>
            <div className="activityTable">
              {clients.slice(0, 6).map((client) => (
                <div key={client.id}>
                  <b>{client.username}</b>
                  <span>{fmtGiB(client.lifetime_usage_bytes)} مصرف · {client.status}</span>
                  <time>{client.quota_bytes ? fmtGiB(client.quota_bytes) : "∞"}</time>
                </div>
              ))}
              {!clients.length && <div><b>سیستم</b><span>برای شروع یک PasarGuard وصل و پلن تعریف کن.</span><time>آماده</time></div>}
            </div>
          </article>
        </section>
      </section>
    </main>
  );
}
