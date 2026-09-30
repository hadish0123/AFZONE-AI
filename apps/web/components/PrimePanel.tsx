"use client";

import {
  Activity,
  Bot,
  Boxes,
  Check,
  CircleDollarSign,
  Copy,
  Gauge,
  LayoutDashboard,
  LogOut,
  RefreshCw,
  Server,
  Settings,
  ShieldCheck,
  Users,
  WalletCards,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { authApi, authBlob, logout, SessionUser } from "../lib/api";

type Summary = {
  role: "owner" | "admin";
  admins: number | null;
  clients: number;
  lifetime_usage_bytes: number;
  orders: number;
  paid_volume_toman: string;
  wallet_balance_toman: string;
  pending_payments: number;
};

type AdminRow = {
  id: string;
  username: string;
  display_name?: string | null;
  status: string;
  wallet_balance_toman: string;
};

type PlanRow = {
  id: string;
  name: string;
  group_id: string;
  enabled?: boolean;
  base_price_per_gib_toman?: string;
  cost_per_gib_toman?: string;
  retail_price_per_gib_toman?: string;
  min_quota_gib?: string | null;
  max_quota_gib?: string | null;
  max_duration_days?: number | null;
  default_hwid_limit?: number | null;
  bot_visible?: boolean;
};

type GroupRow = {
  id: string;
  connection_id: string;
  remote_group_id: number;
  name: string;
  enabled: boolean;
  inbound_tags: string[];
};

type ClientRow = {
  id: string;
  admin_id: string;
  username: string;
  status: string;
  quota_bytes: number | null;
  expires_at?: string | null;
  hwid_limit?: number | null;
  lifetime_usage_bytes: number;
  subscription_url?: string | null;
  plan_id?: string | null;
};

type PaymentRow = {
  id: string;
  admin_id: string;
  customer_id?: string | null;
  order_id?: string | null;
  method: string;
  status: string;
  amount_toman: string;
  purpose?: string | null;
  created_at: string;
};

type BotRow = {
  id: string;
  admin_id: string;
  name: string;
  username?: string | null;
  enabled: boolean;
  customer_wallet_enabled: boolean;
  card_to_card_enabled: boolean;
  gateway_enabled: boolean;
};

type ConnectionRow = {
  id: string;
  name: string;
  base_url: string;
  enabled: boolean;
  last_sync_at?: string | null;
  last_error?: string | null;
};

type TxRow = {
  id: string;
  type: string;
  amount_toman: string;
  balance_after_toman: string;
  description?: string | null;
  created_at: string;
};

type OrderRow = {
  id: string;
  admin_id: string;
  customer_id?: string | null;
  plan_id: string;
  quota_bytes: number;
  duration_days?: number | null;
  retail_amount_toman: string;
  payment_method: string;
  status: string;
  client_id?: string | null;
  created_at: string;
};

type CustomerRow = {
  id: string;
  admin_id: string;
  username?: string | null;
  display_name?: string | null;
  telegram_user_id?: number | null;
  wallet_balance_toman: string;
};

type NotificationRow = {
  id: string;
  kind: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
};

type Financial = {
  sales_toman: string;
  actual_usage_cost_toman: string;
  gross_margin_toman: string;
  provisioned_orders: number;
};

type PaymentProfile = {
  card_number?: string | null;
  card_holder_name?: string | null;
  card_instructions?: string | null;
  card_to_card_enabled: boolean;
  gateway_provider?: string | null;
  gateway_enabled: boolean;
  gateway_configured: boolean;
};

type AuditRow = {
  id: string;
  action: string;
  entity_type: string;
  entity_id?: string | null;
  ip_address?: string | null;
  created_at: string;
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
  [Activity, "گزارش‌ها"],
  [Settings, "تنظیمات"],
] as const;

const money = (value?: string | number | null) =>
  new Intl.NumberFormat("fa-IR").format(Number(value || 0)) + " تومان";
const gib = (bytes?: number | null) =>
  (Number(bytes || 0) / 1024 ** 3).toLocaleString("fa-IR", { maximumFractionDigits: 2 }) + " GB";
const dt = (value?: string | null) => value ? new Date(value).toLocaleString("fa-IR") : "—";

export default function PrimePanel({
  user,
  onSessionExpired,
}: {
  user: SessionUser;
  onSessionExpired: () => void;
}) {
  const [active, setActive] = useState("داشبورد");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const [summary, setSummary] = useState<Summary | null>(null);
  const [admins, setAdmins] = useState<AdminRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [groups, setGroups] = useState<GroupRow[]>([]);
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [payments, setPayments] = useState<PaymentRow[]>([]);
  const [bots, setBots] = useState<BotRow[]>([]);
  const [connections, setConnections] = useState<ConnectionRow[]>([]);
  const [transactions, setTransactions] = useState<TxRow[]>([]);
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [customers, setCustomers] = useState<CustomerRow[]>([]);
  const [notifications, setNotifications] = useState<NotificationRow[]>([]);
  const [financial, setFinancial] = useState<Financial | null>(null);
  const [paymentProfile, setPaymentProfile] = useState<PaymentProfile | null>(null);
  const [twoFactor, setTwoFactor] = useState<{ enabled: boolean; recovery_codes_remaining: number } | null>(null);
  const [audits, setAudits] = useState<AuditRow[]>([]);

  const [adminForm, setAdminForm] = useState({ username: "", password: "", display_name: "", initial_balance_toman: "0" });
  const [connectionForm, setConnectionForm] = useState({ name: "", base_url: "", api_token: "" });
  const [planForm, setPlanForm] = useState({ name: "", group_id: "", base_price_per_gib_toman: "", min_quota_gib: "1", max_quota_gib: "", max_duration_days: "365", default_hwid_limit: "1" });
  const [clientForm, setClientForm] = useState({ username: "", admin_id: "", plan_id: "", quota_gib: "50", duration_days: "30", hwid_limit: "1" });
  const [botForm, setBotForm] = useState({ name: "", token: "", admin_id: "", customer_wallet_enabled: true, card_to_card_enabled: true, gateway_enabled: false });
  const [profileForm, setProfileForm] = useState({ card_number: "", card_holder_name: "", card_instructions: "", card_to_card_enabled: true, gateway_enabled: false, merchant_id: "" });
  const [walletTopup, setWalletTopup] = useState("100000");
  const [walletReceipt, setWalletReceipt] = useState<File | null>(null);
  const [assign, setAssign] = useState<Record<string, { adminId: string; price: string }>>({});
  const [retail, setRetail] = useState<Record<string, string>>({});
  const [adminCredit, setAdminCredit] = useState<Record<string, string>>({});

  async function load() {
    setBusy(true);
    setError("");
    try {
      const common = await Promise.all([
        authApi<Summary>("/api/v1/dashboard/summary"),
        authApi<ClientRow[]>("/api/v1/clients"),
        authApi<PlanRow[]>("/api/v1/plans"),
        authApi<GroupRow[]>("/api/v1/groups"),
        authApi<PaymentRow[]>("/api/v1/payments"),
        authApi<BotRow[]>("/api/v1/bots"),
        authApi<TxRow[]>("/api/v1/wallet/transactions"),
        authApi<OrderRow[]>("/api/v1/orders"),
        authApi<CustomerRow[]>("/api/v1/customers"),
        authApi<NotificationRow[]>("/api/v1/notifications"),
        authApi<Financial>("/api/v1/reports/financial"),
        authApi<PaymentProfile>("/api/v1/payment-profile"),
        authApi<{ enabled: boolean; recovery_codes_remaining: number }>("/api/v1/security/2fa/status"),
      ]);
      setSummary(common[0]);
      setClients(common[1]);
      setPlans(common[2]);
      setGroups(common[3]);
      setPayments(common[4]);
      setBots(common[5]);
      setTransactions(common[6]);
      setOrders(common[7]);
      setCustomers(common[8]);
      setNotifications(common[9]);
      setFinancial(common[10]);
      setPaymentProfile(common[11]);
      setTwoFactor(common[12]);
      setProfileForm((old) => ({
        ...old,
        card_number: common[11].card_number || "",
        card_holder_name: common[11].card_holder_name || "",
        card_instructions: common[11].card_instructions || "",
        card_to_card_enabled: common[11].card_to_card_enabled,
        gateway_enabled: common[11].gateway_enabled,
      }));

      if (user.role === "owner") {
        const owner = await Promise.all([
          authApi<AdminRow[]>("/api/v1/admins"),
          authApi<ConnectionRow[]>("/api/v1/connections"),
          authApi<AuditRow[]>("/api/v1/audit-logs?limit=100"),
        ]);
        setAdmins(owner[0]);
        setConnections(owner[1]);
        setAudits(owner[2]);
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : "خطا در دریافت اطلاعات";
      if (message === "session_expired") onSessionExpired();
      else setError(message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function run(fn: () => Promise<unknown>, success = "انجام شد") {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      setNotice(success);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "عملیات ناموفق بود");
      setBusy(false);
    }
  }

  async function signOut() {
    await logout();
    onSessionExpired();
  }

  const unread = useMemo(() => notifications.filter((n) => !n.is_read).length, [notifications]);
  const activeClients = useMemo(() => clients.filter((c) => c.status === "active").length, [clients]);

  function copy(value?: string | null) {
    if (!value) return;
    navigator.clipboard.writeText(value);
    setNotice("کپی شد");
  }

  async function createAdmin(e: FormEvent) {
    e.preventDefault();
    await run(() => authApi("/api/v1/admins", {
      method: "POST",
      body: JSON.stringify({
        ...adminForm,
        initial_balance_toman: Number(adminForm.initial_balance_toman || 0),
      }),
    }), "نماینده ساخته شد");
    setAdminForm({ username: "", password: "", display_name: "", initial_balance_toman: "0" });
  }

  async function createConnection(e: FormEvent) {
    e.preventDefault();
    await run(() => authApi("/api/v1/connections", {
      method: "POST",
      body: JSON.stringify(connectionForm),
    }), "اتصال PasarGuard اضافه شد");
    setConnectionForm({ name: "", base_url: "", api_token: "" });
  }

  async function createPlan(e: FormEvent) {
    e.preventDefault();
    await run(() => authApi("/api/v1/plans", {
      method: "POST",
      body: JSON.stringify({
        name: planForm.name,
        group_id: planForm.group_id,
        base_price_per_gib_toman: Number(planForm.base_price_per_gib_toman),
        min_quota_gib: planForm.min_quota_gib ? Number(planForm.min_quota_gib) : null,
        max_quota_gib: planForm.max_quota_gib ? Number(planForm.max_quota_gib) : null,
        max_duration_days: planForm.max_duration_days ? Number(planForm.max_duration_days) : null,
        default_hwid_limit: planForm.default_hwid_limit ? Number(planForm.default_hwid_limit) : null,
      }),
    }), "پلن ساخته شد");
    setPlanForm({ name: "", group_id: "", base_price_per_gib_toman: "", min_quota_gib: "1", max_quota_gib: "", max_duration_days: "365", default_hwid_limit: "1" });
  }

  async function createClient(e: FormEvent) {
    e.preventDefault();
    await run(() => authApi("/api/v1/clients", {
      method: "POST",
      body: JSON.stringify({
        username: clientForm.username,
        admin_id: user.role === "owner" ? clientForm.admin_id : null,
        plan_id: clientForm.plan_id,
        quota_gib: Number(clientForm.quota_gib),
        duration_days: clientForm.duration_days ? Number(clientForm.duration_days) : null,
        hwid_limit: clientForm.hwid_limit ? Number(clientForm.hwid_limit) : null,
      }),
    }), "کلاینت روی PasarGuard ساخته شد");
    setClientForm((v) => ({ ...v, username: "" }));
  }

  async function createBot(e: FormEvent) {
    e.preventDefault();
    await run(() => authApi("/api/v1/bots", {
      method: "POST",
      body: JSON.stringify({
        ...botForm,
        admin_id: user.role === "owner" ? botForm.admin_id : null,
      }),
    }), "ربات ثبت و توسط Telegram تأیید شد");
    setBotForm({ name: "", token: "", admin_id: "", customer_wallet_enabled: true, card_to_card_enabled: true, gateway_enabled: false });
  }

  async function saveProfile(e: FormEvent) {
    e.preventDefault();
    const payload: Record<string, unknown> = {
      card_number: profileForm.card_number || null,
      card_holder_name: profileForm.card_holder_name || null,
      card_instructions: profileForm.card_instructions || null,
      card_to_card_enabled: profileForm.card_to_card_enabled,
      gateway_provider: "zarinpal",
      gateway_enabled: profileForm.gateway_enabled,
    };
    if (profileForm.merchant_id) {
      payload.gateway_credentials = { merchant_id: profileForm.merchant_id };
    }
    await run(() => authApi("/api/v1/payment-profile", {
      method: "PUT",
      body: JSON.stringify(payload),
    }), "تنظیمات پرداخت ذخیره شد");
    setProfileForm((v) => ({ ...v, merchant_id: "" }));
  }

  async function viewReceipt(id: string) {
    try {
      const blob = await authBlob(`/api/v1/payments/${id}/receipt`);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "رسید قابل دریافت نیست");
    }
  }

  async function cardWalletTopup(e: FormEvent) {
    e.preventDefault();
    if (!walletReceipt) return setError("فایل رسید را انتخاب کنید");
    const fd = new FormData();
    fd.append("amount_toman", walletTopup);
    fd.append("receipt", walletReceipt);
    await run(() => authApi("/api/v1/wallet/topups/card", { method: "POST", body: fd }), "رسید شارژ ثبت شد");
    setWalletReceipt(null);
  }

  function SectionTitle({ title, sub }: { title: string; sub: string }) {
    return <div className="sectionTitle"><div><h2>{title}</h2><p>{sub}</p></div></div>;
  }

  function Overview() {
    const cards = user.role === "owner"
      ? [
          ["نمایندگان", summary?.admins || 0, "Owner"],
          ["کلاینت‌های فعال", activeClients, `${summary?.clients || 0} کل`],
          ["مصرف Lifetime", gib(summary?.lifetime_usage_bytes), "Billing"],
          ["پرداخت منتظر", summary?.pending_payments || 0, "Review"],
        ]
      : [
          ["موجودی کیف پول", money(summary?.wallet_balance_toman), "Live"],
          ["کلاینت‌های فعال", activeClients, `${summary?.clients || 0} کل`],
          ["مصرف Lifetime", gib(summary?.lifetime_usage_bytes), "Billing"],
          ["سفارش‌ها", summary?.orders || 0, "Sales"],
        ];

    return <>
      <section className="metrics">
        {cards.map(([title, value, meta], i) => <article className={"metric metric" + i} key={String(title)}>
          <div className="metricTop"><span>{title}</span><span className="pill">{meta}</span></div>
          <strong>{String(value)}</strong><div className="spark"><i/><i/><i/><i/><i/><i/><i/></div>
        </article>)}
      </section>
      <section className="grid">
        <article className="panel">
          <SectionTitle title="وضعیت سیستم" sub="هسته‌های اصلی PRIMEVPN" />
          {[
            ["API PRIMEVPN", true],
            ["Billing Worker", true],
            ["Telegram Worker", true],
            ["PostgreSQL / Redis", true],
            ["PasarGuard", user.role === "admin" || connections.some((x) => x.enabled)],
          ].map(([name, ok]) => <div className="statusRow" key={String(name)}>
            <span><i className={ok ? "dot" : "dot amber"}/>{name}</span><b>{ok ? "آماده" : "منتظر اتصال"}</b>
          </div>)}
        </article>
        <article className="panel">
          <SectionTitle title="هشدارها" sub={`${unread} پیام خوانده‌نشده`} />
          <div className="compactList">
            {notifications.slice(0, 6).map((n) => <button className="listButton" key={n.id} onClick={() => !n.is_read && run(() => authApi(`/api/v1/notifications/${n.id}/read`, { method: "POST" }), "خوانده شد")}>
              <div><strong>{n.title}</strong><span>{n.message}</span></div><span className={n.is_read ? "tag" : "tag hot"}>{n.is_read ? "خوانده‌شده" : "جدید"}</span>
            </button>)}
            {!notifications.length && <div className="emptyMini">هشداری وجود ندارد.</div>}
          </div>
        </article>
        <article className="panel widePanel">
          <SectionTitle title="خلاصه مالی" sub="فروش در برابر هزینه مصرف واقعی" />
          <div className="financeGrid">
            <div><span>فروش ثبت‌شده</span><strong>{money(financial?.sales_toman)}</strong></div>
            <div><span>هزینه مصرف واقعی</span><strong>{money(financial?.actual_usage_cost_toman)}</strong></div>
            <div><span>حاشیه ناخالص</span><strong>{money(financial?.gross_margin_toman)}</strong></div>
            <div><span>سفارش Provision شده</span><strong>{financial?.provisioned_orders || 0}</strong></div>
          </div>
        </article>
      </section>
    </>;
  }

  function Admins() {
    if (user.role !== "owner") return <article className="panel"><div className="emptyMini">این بخش فقط برای مالک است.</div></article>;
    return <section className="stack">
      <article className="panel">
        <SectionTitle title="ساخت نماینده" sub="حساب مستقل با کیف پول و دسترسی محدود" />
        <form className="formGrid" onSubmit={createAdmin}>
          <input placeholder="نام کاربری" value={adminForm.username} onChange={(e) => setAdminForm({ ...adminForm, username: e.target.value })} required />
          <input placeholder="نام نمایشی" value={adminForm.display_name} onChange={(e) => setAdminForm({ ...adminForm, display_name: e.target.value })} />
          <input placeholder="رمز عبور حداقل ۱۰ کاراکتر" type="password" value={adminForm.password} onChange={(e) => setAdminForm({ ...adminForm, password: e.target.value })} required />
          <input placeholder="موجودی اولیه تومان" type="number" value={adminForm.initial_balance_toman} onChange={(e) => setAdminForm({ ...adminForm, initial_balance_toman: e.target.value })} />
          <button className="primary" disabled={busy}>ساخت نماینده</button>
        </form>
      </article>
      <article className="panel">
        <SectionTitle title="نمایندگان" sub={`${admins.length} حساب`} />
        <div className="dataTable">
          {admins.map((a) => <div className="dataRow" key={a.id}>
            <div><strong>{a.display_name || a.username}</strong><span>@{a.username} · {a.status}</span></div>
            <div><b>{money(a.wallet_balance_toman)}</b></div>
            <div className="inlineActions">
              <input className="miniInput" placeholder="شارژ" type="number" value={adminCredit[a.id] || ""} onChange={(e) => setAdminCredit({ ...adminCredit, [a.id]: e.target.value })} />
              <button onClick={() => run(() => authApi(`/api/v1/admins/${a.id}/wallet/topup`, { method: "POST", body: JSON.stringify({ amount_toman: Number(adminCredit[a.id] || 0), note: "Owner top-up from PRIMEVPN panel" }) }), "کیف پول شارژ شد")}>شارژ</button>
              <button className={a.status === "active" ? "dangerSoft" : "okSoft"} onClick={() => run(() => authApi(`/api/v1/admins/${a.id}`, { method: "PATCH", body: JSON.stringify({ status: a.status === "active" ? "disabled" : "active" }) }), "وضعیت نماینده تغییر کرد")}>{a.status === "active" ? "غیرفعال" : "فعال"}</button>
            </div>
          </div>)}
          {!admins.length && <div className="emptyMini">نماینده‌ای ساخته نشده.</div>}
        </div>
      </article>
    </section>;
  }

  function Clients() {
    return <section className="stack">
      <article className="panel">
        <SectionTitle title="ساخت کلاینت" sub="ساخت مستقیم روی PasarGuard با Plan مجاز" />
        <form className="formGrid" onSubmit={createClient}>
          <input placeholder="Username" value={clientForm.username} onChange={(e) => setClientForm({ ...clientForm, username: e.target.value })} required />
          {user.role === "owner" && <select value={clientForm.admin_id} onChange={(e) => setClientForm({ ...clientForm, admin_id: e.target.value })} required><option value="">نماینده</option>{admins.map((a) => <option key={a.id} value={a.id}>{a.username}</option>)}</select>}
          <select value={clientForm.plan_id} onChange={(e) => setClientForm({ ...clientForm, plan_id: e.target.value })} required><option value="">پلن</option>{plans.filter((p) => p.enabled !== false).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
          <input type="number" step="0.1" placeholder="حجم GB" value={clientForm.quota_gib} onChange={(e) => setClientForm({ ...clientForm, quota_gib: e.target.value })} required />
          <input type="number" placeholder="مدت روز" value={clientForm.duration_days} onChange={(e) => setClientForm({ ...clientForm, duration_days: e.target.value })} />
          <input type="number" placeholder="تعداد دستگاه" value={clientForm.hwid_limit} onChange={(e) => setClientForm({ ...clientForm, hwid_limit: e.target.value })} />
          <button className="primary" disabled={busy}>ساخت کلاینت</button>
        </form>
      </article>
      <article className="panel">
        <SectionTitle title="کلاینت‌ها" sub={`${clients.length} سرویس`} />
        <div className="dataTable">
          {clients.map((c) => <div className="dataRow clientRow" key={c.id}>
            <div><strong>{c.username}</strong><span>{c.status} · مصرف {gib(c.lifetime_usage_bytes)} / {c.quota_bytes ? gib(c.quota_bytes) : "∞"}</span></div>
            <div><span>{c.expires_at ? dt(c.expires_at) : "بدون انقضا"} · {c.hwid_limit || "∞"} دستگاه</span></div>
            <div className="inlineActions">
              <button title="کپی لینک" onClick={() => copy(c.subscription_url)}><Copy size={14}/></button>
              <button onClick={() => run(() => authApi(`/api/v1/clients/${c.id}/reset-usage`, { method: "POST" }), "مصرف Reset شد")}>Reset</button>
              <button onClick={() => run(() => authApi(`/api/v1/clients/${c.id}/revoke-subscription`, { method: "POST" }), "Subscription عوض شد")}>Revoke</button>
              <button onClick={() => run(() => authApi(`/api/v1/clients/${c.id}`, { method: "PATCH", body: JSON.stringify({ disabled: c.status === "active" }) }), "وضعیت کلاینت تغییر کرد")}>{c.status === "active" ? "Disable" : "Enable"}</button>
            </div>
          </div>)}
          {!clients.length && <div className="emptyMini">هنوز کلاینتی وجود ندارد.</div>}
        </div>
      </article>
    </section>;
  }

  function Plans() {
    return <section className="stack">
      {user.role === "owner" && <article className="panel">
        <SectionTitle title="پلن پایه" sub="هر Plan به یک Group و قیمت پایه هر گیگ متصل است" />
        <form className="formGrid" onSubmit={createPlan}>
          <input placeholder="نام پلن" value={planForm.name} onChange={(e) => setPlanForm({ ...planForm, name: e.target.value })} required />
          <select value={planForm.group_id} onChange={(e) => setPlanForm({ ...planForm, group_id: e.target.value })} required><option value="">Group</option>{groups.filter((g) => g.enabled).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select>
          <input type="number" placeholder="قیمت پایه هر GB تومان" value={planForm.base_price_per_gib_toman} onChange={(e) => setPlanForm({ ...planForm, base_price_per_gib_toman: e.target.value })} required />
          <input type="number" placeholder="حداقل GB" value={planForm.min_quota_gib} onChange={(e) => setPlanForm({ ...planForm, min_quota_gib: e.target.value })} />
          <input type="number" placeholder="حداکثر GB" value={planForm.max_quota_gib} onChange={(e) => setPlanForm({ ...planForm, max_quota_gib: e.target.value })} />
          <input type="number" placeholder="حداکثر روز" value={planForm.max_duration_days} onChange={(e) => setPlanForm({ ...planForm, max_duration_days: e.target.value })} />
          <input type="number" placeholder="HWID پیش‌فرض" value={planForm.default_hwid_limit} onChange={(e) => setPlanForm({ ...planForm, default_hwid_limit: e.target.value })} />
          <button className="primary">ساخت پلن</button>
        </form>
      </article>}
      <article className="panel">
        <SectionTitle title="پلن‌ها" sub={user.role === "owner" ? "تخصیص به نماینده و تعیین قیمت فروش" : "فقط قیمت فروش خودت را می‌توانی افزایش بدهی"} />
        <div className="dataTable">
          {plans.map((p) => <div className="dataRow planRow" key={p.id}>
            <div><strong>{p.name}</strong><span>پایه: {money(p.base_price_per_gib_toman || p.cost_per_gib_toman)} · {p.enabled === false ? "خاموش" : "فعال"}</span></div>
            {user.role === "owner" ? <div className="inlineActions grow">
              <select value={assign[p.id]?.adminId || ""} onChange={(e) => setAssign({ ...assign, [p.id]: { adminId: e.target.value, price: assign[p.id]?.price || p.base_price_per_gib_toman || "" } })}><option value="">نماینده</option>{admins.map((a) => <option key={a.id} value={a.id}>{a.username}</option>)}</select>
              <input className="miniInput" type="number" placeholder="قیمت فروش" value={assign[p.id]?.price || ""} onChange={(e) => setAssign({ ...assign, [p.id]: { adminId: assign[p.id]?.adminId || "", price: e.target.value } })} />
              <button onClick={() => run(() => authApi(`/api/v1/admins/${assign[p.id]?.adminId}/plans/${p.id}`, { method: "PUT", body: JSON.stringify({ retail_price_per_gib_toman: Number(assign[p.id]?.price || 0), bot_visible: true }) }), "پلن به نماینده تخصیص داده شد")}>تخصیص</button>
              <button className="dangerSoft" onClick={() => run(() => authApi(`/api/v1/plans/${p.id}`, { method: "DELETE" }), "پلن خاموش شد")}>خاموش</button>
            </div> : <div className="inlineActions grow">
              <input className="miniInput" type="number" value={retail[p.id] ?? p.retail_price_per_gib_toman ?? ""} onChange={(e) => setRetail({ ...retail, [p.id]: e.target.value })} />
              <button onClick={() => run(() => authApi(`/api/v1/my-plans/${p.id}/retail-price`, { method: "PATCH", body: JSON.stringify({ retail_price_per_gib_toman: Number(retail[p.id] ?? p.retail_price_per_gib_toman) }) }), "قیمت فروش ذخیره شد")}>ذخیره قیمت</button>
            </div>}
          </div>)}
        </div>
      </article>
      <article className="panel">
        <SectionTitle title="Groupها" sub="خوانده‌شده از PasarGuard" />
        <div className="chips">{groups.map((g) => <span className="chip" key={g.id}>{g.name} · #{g.remote_group_id}</span>)}</div>
      </article>
    </section>;
  }

  function Wallet() {
    return <section className="stack">
      <article className="panel">
        <SectionTitle title="کیف پول" sub="Ledger منبع اصلی حسابداری است" />
        <div className="walletHero"><span>موجودی فعلی</span><strong>{money(summary?.wallet_balance_toman)}</strong></div>
        {user.role === "admin" && <div className="dualForms">
          <form className="subForm" onSubmit={(e) => { e.preventDefault(); run(async () => {
            const result = await authApi<{ redirect_url: string }>("/api/v1/wallet/topups/gateway", { method: "POST", body: JSON.stringify({ amount_toman: Number(walletTopup) }) });
            window.open(result.redirect_url, "_blank", "noopener,noreferrer");
          }, "لینک درگاه ایجاد شد"); }}>
            <h3>شارژ با درگاه</h3><input type="number" value={walletTopup} onChange={(e) => setWalletTopup(e.target.value)} /><button className="primary">رفتن به درگاه</button>
          </form>
          <form className="subForm" onSubmit={cardWalletTopup}>
            <h3>شارژ کارت‌به‌کارت</h3><input type="number" value={walletTopup} onChange={(e) => setWalletTopup(e.target.value)} /><input type="file" accept="image/*,.pdf" onChange={(e) => setWalletReceipt(e.target.files?.[0] || null)} /><button>ارسال رسید</button>
          </form>
        </div>}
      </article>
      <article className="panel">
        <SectionTitle title="گردش کیف پول" sub={`${transactions.length} تراکنش آخر`} />
        <div className="dataTable">
          {transactions.map((t) => <div className="dataRow" key={t.id}><div><strong>{t.type}</strong><span>{t.description || "—"} · {dt(t.created_at)}</span></div><div className={Number(t.amount_toman) >= 0 ? "positive" : "negative"}><b>{money(t.amount_toman)}</b><span>مانده {money(t.balance_after_toman)}</span></div></div>)}
        </div>
      </article>
    </section>;
  }

  function Payments() {
    return <section className="stack">
      <article className="panel">
        <SectionTitle title="پرداخت‌ها" sub="درگاه، کارت‌به‌کارت و کیف پول" />
        <div className="dataTable">
          {payments.map((p) => <div className="dataRow" key={p.id}>
            <div><strong>{money(p.amount_toman)}</strong><span>{p.method} · {p.purpose || "payment"} · {dt(p.created_at)}</span></div>
            <div><span className={"tag " + (p.status === "paid" ? "ok" : p.status === "awaiting_review" ? "hot" : "")}>{p.status}</span></div>
            <div className="inlineActions">
              {p.method === "card_to_card" && <button onClick={() => viewReceipt(p.id)}>رسید</button>}
              {p.status === "awaiting_review" && <>
                <button className="okSoft" onClick={() => run(() => authApi(`/api/v1/payments/${p.id}/review`, { method: "POST", body: JSON.stringify({ approved: true, note: "Approved from panel" }) }), "پرداخت تأیید شد")}><Check size={14}/> تأیید</button>
                <button className="dangerSoft" onClick={() => run(() => authApi(`/api/v1/payments/${p.id}/review`, { method: "POST", body: JSON.stringify({ approved: false, note: "Rejected from panel" }) }), "پرداخت رد شد")}><X size={14}/> رد</button>
              </>}
            </div>
          </div>)}
        </div>
      </article>
      <article className="panel">
        <SectionTitle title="سفارش‌ها" sub={`${orders.length} سفارش`} />
        <div className="dataTable">
          {orders.slice(0, 100).map((o) => <div className="dataRow" key={o.id}><div><strong>{money(o.retail_amount_toman)}</strong><span>{gib(o.quota_bytes)} · {o.duration_days ? o.duration_days + " روز" : "بدون انقضا"} · {o.payment_method}</span></div><span className="tag">{o.status}</span></div>)}
        </div>
      </article>
      <article className="panel">
        <SectionTitle title="مشتری‌ها" sub={`${customers.length} مشتری`} />
        <div className="chips">{customers.slice(0, 50).map((c) => <span className="chip" key={c.id}>{c.display_name || c.username || c.telegram_user_id} · {money(c.wallet_balance_toman)}</span>)}</div>
      </article>
    </section>;
  }

  function Bots() {
    return <section className="stack">
      <article className="panel">
        <SectionTitle title="ثبت ربات فروش" sub="Token اعتبارسنجی و رمزگذاری می‌شود" />
        <form className="formGrid" onSubmit={createBot}>
          <input placeholder="نام ربات" value={botForm.name} onChange={(e) => setBotForm({ ...botForm, name: e.target.value })} required />
          <input placeholder="Bot Token" type="password" value={botForm.token} onChange={(e) => setBotForm({ ...botForm, token: e.target.value })} required />
          {user.role === "owner" && <select value={botForm.admin_id} onChange={(e) => setBotForm({ ...botForm, admin_id: e.target.value })} required><option value="">نماینده</option>{admins.map((a) => <option key={a.id} value={a.id}>{a.username}</option>)}</select>}
          <label className="check"><input type="checkbox" checked={botForm.customer_wallet_enabled} onChange={(e) => setBotForm({ ...botForm, customer_wallet_enabled: e.target.checked })}/> کیف پول مشتری</label>
          <label className="check"><input type="checkbox" checked={botForm.card_to_card_enabled} onChange={(e) => setBotForm({ ...botForm, card_to_card_enabled: e.target.checked })}/> کارت‌به‌کارت</label>
          <label className="check"><input type="checkbox" checked={botForm.gateway_enabled} onChange={(e) => setBotForm({ ...botForm, gateway_enabled: e.target.checked })}/> درگاه</label>
          <button className="primary">ثبت ربات</button>
        </form>
      </article>
      <article className="panel">
        <SectionTitle title="ربات‌ها" sub="Telegram Worker به‌صورت خودکار ربات‌های فعال را اجرا می‌کند" />
        <div className="dataTable">
          {bots.map((b) => <div className="dataRow" key={b.id}><div><strong>{b.name}</strong><span>@{b.username || "—"} · {b.enabled ? "فعال" : "خاموش"}</span></div><div className="inlineActions"><span className="tag">{b.customer_wallet_enabled ? "Wallet" : ""}</span><span className="tag">{b.card_to_card_enabled ? "Card" : ""}</span><span className="tag">{b.gateway_enabled ? "Gateway" : ""}</span>{b.enabled && <button className="dangerSoft" onClick={() => run(() => authApi(`/api/v1/bots/${b.id}`, { method: "DELETE" }), "ربات غیرفعال شد")}>خاموش</button>}</div></div>)}
        </div>
      </article>
    </section>;
  }

  function Pasarguard() {
    if (user.role !== "owner") return <article className="panel"><SectionTitle title="PasarGuard" sub="اتصال توسط مالک مدیریت می‌شود" /><div className="emptyMini">Groupها و Planهای مجاز شما به‌صورت خودکار نمایش داده می‌شوند.</div></article>;
    return <section className="stack">
      <article className="panel">
        <SectionTitle title="افزودن PasarGuard" sub="Panel URL + API Token" />
        <form className="formGrid" onSubmit={createConnection}>
          <input placeholder="نام اتصال" value={connectionForm.name} onChange={(e) => setConnectionForm({ ...connectionForm, name: e.target.value })} required />
          <input placeholder="https://panel.example.com" value={connectionForm.base_url} onChange={(e) => setConnectionForm({ ...connectionForm, base_url: e.target.value })} required />
          <input type="password" placeholder="API Token" value={connectionForm.api_token} onChange={(e) => setConnectionForm({ ...connectionForm, api_token: e.target.value })} required />
          <button className="primary">تست و اضافه‌کردن</button>
        </form>
      </article>
      <article className="panel">
        <SectionTitle title="اتصال‌ها" sub="Multi-PasarGuard" />
        <div className="dataTable">
          {connections.map((c) => <div className="dataRow" key={c.id}><div><strong>{c.name}</strong><span>{c.base_url} · Sync: {dt(c.last_sync_at)}</span>{c.last_error && <small className="negative">{c.last_error}</small>}</div><div className="inlineActions"><button onClick={() => run(() => authApi(`/api/v1/connections/${c.id}/test`, { method: "POST" }), "اتصال سالم است")}>Test</button><button onClick={() => run(() => authApi(`/api/v1/connections/${c.id}/sync-groups`, { method: "POST" }), "Groupها Sync شدند")}>Sync Groups</button>{c.enabled && <button className="dangerSoft" onClick={() => run(() => authApi(`/api/v1/connections/${c.id}`, { method: "DELETE" }), "اتصال غیرفعال شد")}>Disable</button>}</div></div>)}
        </div>
      </article>
    </section>;
  }

  function Reports() {
    return <section className="stack">
      <article className="panel"><SectionTitle title="گزارش مالی" sub="فروش منهای هزینه واقعی مصرف" /><div className="financeGrid"><div><span>فروش</span><strong>{money(financial?.sales_toman)}</strong></div><div><span>هزینه مصرف</span><strong>{money(financial?.actual_usage_cost_toman)}</strong></div><div><span>سود ناخالص</span><strong>{money(financial?.gross_margin_toman)}</strong></div><div><span>سفارش موفق</span><strong>{financial?.provisioned_orders || 0}</strong></div></div></article>
      {user.role === "owner" && <article className="panel"><SectionTitle title="Audit Log" sub="ردیابی عملیات حساس" /><div className="dataTable">{audits.map((a) => <div className="dataRow" key={a.id}><div><strong>{a.action}</strong><span>{a.entity_type} · {a.entity_id || "—"} · {dt(a.created_at)}</span></div><span>{a.ip_address || "—"}</span></div>)}</div></article>}
    </section>;
  }

  function SettingsView() {
    return <section className="stack">
      <article className="panel">
        <SectionTitle title="روش‌های پرداخت" sub="کارت و درگاه مختص حساب شما" />
        <form className="formGrid" onSubmit={saveProfile}>
          <input placeholder="شماره کارت" value={profileForm.card_number} onChange={(e) => setProfileForm({ ...profileForm, card_number: e.target.value })} />
          <input placeholder="نام صاحب کارت" value={profileForm.card_holder_name} onChange={(e) => setProfileForm({ ...profileForm, card_holder_name: e.target.value })} />
          <input placeholder="توضیح کارت‌به‌کارت" value={profileForm.card_instructions} onChange={(e) => setProfileForm({ ...profileForm, card_instructions: e.target.value })} />
          <input type="password" placeholder={paymentProfile?.gateway_configured ? "Merchant ID زرین‌پال (برای تغییر وارد کن)" : "Merchant ID زرین‌پال"} value={profileForm.merchant_id} onChange={(e) => setProfileForm({ ...profileForm, merchant_id: e.target.value })} />
          <label className="check"><input type="checkbox" checked={profileForm.card_to_card_enabled} onChange={(e) => setProfileForm({ ...profileForm, card_to_card_enabled: e.target.checked })}/> کارت‌به‌کارت فعال</label>
          <label className="check"><input type="checkbox" checked={profileForm.gateway_enabled} onChange={(e) => setProfileForm({ ...profileForm, gateway_enabled: e.target.checked })}/> زرین‌پال فعال</label>
          <button className="primary">ذخیره تنظیمات</button>
        </form>
      </article>
      {user.role === "owner" && <article className="panel">
        <SectionTitle title="امنیت مالک" sub="TOTP دو مرحله‌ای و Recovery Code" />
        <div className="securityBox">
          <strong>2FA: {twoFactor?.enabled ? "فعال" : "غیرفعال"}</strong>
          <span>Recovery باقی‌مانده: {twoFactor?.recovery_codes_remaining || 0}</span>
          {!twoFactor?.enabled ? <button onClick={() => run(async () => {
            const setup = await authApi<{ secret: string; otpauth_uri: string; recovery_codes: string[] }>("/api/v1/security/2fa/setup", { method: "POST" });
            const code = window.prompt(`Secret:\n${setup.secret}\n\nRecovery Codes:\n${setup.recovery_codes.join("  ")}\n\nبعد از افزودن به Authenticator، کد ۶ رقمی را وارد کن:`);
            if (!code) throw new Error("فعال‌سازی لغو شد");
            await authApi("/api/v1/security/2fa/enable", { method: "POST", body: JSON.stringify({ code }) });
          }, "2FA فعال شد")}>راه‌اندازی 2FA</button> : <button className="dangerSoft" onClick={() => {
            const code = window.prompt("کد فعلی Authenticator را وارد کن:");
            if (code) run(() => authApi("/api/v1/security/2fa/disable", { method: "POST", body: JSON.stringify({ code }) }), "2FA غیرفعال شد");
          }}>غیرفعال‌کردن 2FA</button>}
        </div>
      </article>}
    </section>;
  }

  const body =
    active === "داشبورد" ? <Overview/> :
    active === "نمایندگان" ? <Admins/> :
    active === "کلاینت‌ها" ? <Clients/> :
    active === "پلن‌ها و گروه‌ها" ? <Plans/> :
    active === "کیف پول" ? <Wallet/> :
    active === "فروش و پرداخت" ? <Payments/> :
    active === "ربات‌های فروش" ? <Bots/> :
    active === "PasarGuard" ? <Pasarguard/> :
    active === "گزارش‌ها" ? <Reports/> :
    <SettingsView/>;

  return <main className="shell">
    <aside className="sidebar glass">
      <div className="brand"><div className="brandMark"><Gauge size={25}/></div><div><strong>PRIMEVPN</strong><span>{user.role === "owner" ? "Owner Console" : "Admin Console"}</span></div></div>
      <nav>{nav.filter(([, label]) => user.role === "owner" || !["نمایندگان", "PasarGuard"].includes(label)).map(([Icon, label]) => <button className={active === label ? "navItem active" : "navItem"} key={label} onClick={() => setActive(label)}><Icon size={19}/><span>{label}</span>{label === "داشبورد" && unread > 0 && <i className="navBadge">{unread}</i>}</button>)}</nav>
      <div className="ownerCard"><div className="avatar">{(user.display_name || user.username)[0].toUpperCase()}</div><div><strong>{user.display_name || user.username}</strong><span>{user.role}</span></div><button className="iconButton" onClick={signOut}><LogOut size={16}/></button></div>
    </aside>
    <section className="workspace">
      <header><div><p className="eyebrow">PRIME NETWORK · PRODUCTION</p><h1>{active}</h1><p className="muted">{user.role === "owner" ? "مرکز کنترل مالک PRIMEVPN" : "پنل مستقل نماینده"}</p></div><div className="headerActions"><button className="ghost" onClick={load} disabled={busy}><RefreshCw size={15}/>{busy ? "در حال بروزرسانی" : "بروزرسانی"}</button></div></header>
      {error && <div className="pageError">{error}</div>}
      {notice && <div className="pageSuccess">{notice}</div>}
      {body}
    </section>
  </main>;
}
