"use client";

import {
  Activity,
  Bell,
  Bot,
  Boxes,
  Check,
  Code2,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Copy,
  CreditCard,
  Database,
  Gauge,
  LayoutDashboard,
  LogOut,
  Menu,
  MoreVertical,
  Plus,
  RefreshCw,
  Search,
  Send,
  Server,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  Wallet,
  WalletCards,
  X,
} from "lucide-react";
import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { authApi, authBlob, logout, SessionUser } from "../lib/api";

type PageResult<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

type Summary = {
  role: "owner" | "admin";
  admins: number | null;
  clients: number;
  active_clients?: number;
  lifetime_usage_bytes: number;
  orders: number;
  today_orders?: number;
  paid_volume_toman: string;
  today_paid_toman?: string;
  wallet_balance_toman: string;
  pending_payments: number;
};

type AdminRow = {
  id: string;
  username: string;
  display_name?: string | null;
  telegram_id?: number | null;
  status: string;
  wallet_balance_toman: string;
  low_balance_threshold_toman?: string;
  debt_limit_toman?: string;
  client_count: number;
  plan_count?: number;
  created_at: string;
};

type ClientRow = {
  id: string;
  admin_id: string;
  admin_username?: string | null;
  username: string;
  status: string;
  quota_bytes: number | null;
  expires_at?: string | null;
  hwid_limit?: number | null;
  lifetime_usage_bytes: number;
  subscription_url?: string | null;
  plan_id?: string | null;
  group_id: string;
  group_name?: string | null;
  connection_name?: string | null;
  created_at: string;
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

type PaymentRow = {
  id: string;
  admin_id: string;
  admin_username?: string | null;
  customer_id?: string | null;
  customer_name?: string | null;
  order_id?: string | null;
  method: string;
  status: string;
  amount_toman: string;
  provider?: string | null;
  provider_reference?: string | null;
  purpose?: string | null;
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
  created_at?: string;
};

type AdminPlanAssignment = {
  assignment_id: string | null;
  plan_id: string;
  name: string;
  enabled: boolean;
  bot_visible: boolean;
  base_price_per_gib_toman: string;
  retail_price_per_gib_toman: string;
  automatic?: boolean;
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

type BankCardRow = {
  id: string;
  title: string;
  card_number: string;
  card_holder_name?: string | null;
  instructions?: string | null;
  enabled: boolean;
  is_default: boolean;
};

type AuditRow = {
  id: string;
  action: string;
  entity_type: string;
  entity_id?: string | null;
  ip_address?: string | null;
  created_at: string;
};

type TwoFactor = {
  enabled: boolean;
  recovery_codes_remaining: number;
};

type ModalKind =
  | null
  | "admin-create"
  | "admin-manage"
  | "client-create"
  | "client-manage"
  | "plan-create"
  | "plan-manage"
  | "connection-create"
  | "connection-manage"
  | "bot-create"
  | "bot-manage"
  | "bank-card"
  | "qr";

type ActionField = {
  key: string;
  label: string;
  type?: "text" | "number" | "password" | "url";
  placeholder?: string;
  required?: boolean;
};

type ActionDialogState = {
  title: string;
  description?: string;
  notice?: string;
  fields: ActionField[];
  submitLabel: string;
  destructive?: boolean;
  successMessage: string;
  onSubmit: (values: Record<string, string>) => Promise<unknown>;
};

const navigation = [
  { key: "dashboard", label: "داشبورد", icon: LayoutDashboard, owner: true, admin: true },
  { key: "admins", label: "نمایندگان", icon: Users, owner: true, admin: false },
  { key: "clients", label: "کلاینت‌ها", icon: ShieldCheck, owner: true, admin: true },
  { key: "plans", label: "پلن‌ها و گروه‌ها", icon: Boxes, owner: true, admin: true },
  { key: "wallet", label: "کیف پول", icon: WalletCards, owner: true, admin: true },
  { key: "commerce", label: "فروش و پرداخت", icon: CircleDollarSign, owner: true, admin: true },
  { key: "bots", label: "ربات‌های فروش", icon: Bot, owner: true, admin: true },
  { key: "pasarguard", label: "PasarGuard", icon: Server, owner: true, admin: false },
  { key: "reports", label: "گزارش‌ها", icon: Activity, owner: true, admin: true },
  { key: "settings", label: "تنظیمات", icon: Settings, owner: true, admin: true },
] as const;

const money = (value?: string | number | null) =>
  new Intl.NumberFormat("fa-IR").format(Number(value || 0)) + " تومان";

const gib = (bytes?: number | null) =>
  (Number(bytes || 0) / 1024 ** 3).toLocaleString("fa-IR", { maximumFractionDigits: 2 }) + " GB";

const dt = (value?: string | null) =>
  value ? new Date(value).toLocaleString("fa-IR") : "—";

const statusFa = (value?: string | null) => ({
  active: "فعال",
  disabled: "غیرفعال",
  error: "خطا",
  pending: "در انتظار",
  awaiting_review: "در انتظار بررسی",
  paid: "پرداخت‌شده",
  rejected: "ردشده",
  failed: "ناموفق",
  provisioned: "فعال‌شده",
  cancelled: "لغوشده",
}[String(value || "")] || value || "—");

function Modal({
  open,
  title,
  children,
  onClose,
  wide = false,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  if (!open) return null;
  return (
    <div className="v2ModalBackdrop" onMouseDown={onClose}>
      <section
        className={wide ? "v2Modal v2ModalWide" : "v2Modal"}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header>
          <strong>{title}</strong>
          <button className="v2IconButton" onClick={onClose}><X size={19} /></button>
        </header>
        <div className="v2ModalBody">{children}</div>
      </section>
    </div>
  );
}


type PrimeSelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

function PrimeSelect({
  value,
  onChange,
  options,
  placeholder = "انتخاب کنید",
  disabled = false,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  options: PrimeSelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const selected = options.find((item) => item.value === value);

  return (
    <div
      className={`primeSelect ${open ? "open" : ""} ${disabled ? "disabled" : ""} ${className}`}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <button
        type="button"
        className="primeSelectTrigger"
        onClick={() => !disabled && setOpen((old) => !old)}
        aria-expanded={open}
        disabled={disabled}
      >
        <span className={selected ? "" : "placeholder"}>{selected?.label || placeholder}</span>
        <ChevronLeft size={18} />
      </button>
      {open && !disabled && (
        <div className="primeSelectMenu">
          {options.length ? options.map((item) => (
            <button
              key={item.value || "__empty__"}
              type="button"
              disabled={item.disabled}
              className={item.value === value ? "selected" : ""}
              onClick={() => {
                onChange(item.value);
                setOpen(false);
              }}
            >
              <span>{item.label}</span>
              {item.value === value && <Check size={16} />}
            </button>
          )) : <div className="primeSelectEmpty">موردی برای انتخاب وجود ندارد</div>}
        </div>
      )}
    </div>
  );
}

function Pager({
  page,
  pages,
  total,
  onPage,
}: {
  page: number;
  pages: number;
  total: number;
  onPage: (page: number) => void;
}) {
  return (
    <div className="v2Pager">
      <span>{new Intl.NumberFormat("fa-IR").format(total)} رکورد</span>
      <div>
        <button disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronRight size={16} /></button>
        <b>{page.toLocaleString("fa-IR")} / {Math.max(pages, 1).toLocaleString("fa-IR")}</b>
        <button disabled={page >= pages} onClick={() => onPage(page + 1)}><ChevronLeft size={16} /></button>
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="v2Empty">{text}</div>;
}

function Toolbar({
  search,
  onSearch,
  placeholder,
  children,
}: {
  search: string;
  onSearch: (value: string) => void;
  placeholder: string;
  children?: ReactNode;
}) {
  return (
    <div className="v2Toolbar">
      <div className="v2Search">
        <Search size={17} />
        <input
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder={placeholder}
        />
      </div>
      <div className="v2ToolbarActions">{children}</div>
    </div>
  );
}

export default function PrimePanelV2({
  user,
  onSessionExpired,
}: {
  user: SessionUser;
  onSessionExpired: () => void;
}) {
  const [section, setSection] = useState("dashboard");
  const [drawer, setDrawer] = useState(false);
  const [modal, setModal] = useState<ModalKind>(null);
  const [actionDialog, setActionDialog] = useState<ActionDialogState | null>(null);
  const [actionValues, setActionValues] = useState<Record<string, string>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [summary, setSummary] = useState<Summary | null>(null);
  const [financial, setFinancial] = useState<Financial | null>(null);
  const [notifications, setNotifications] = useState<NotificationRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [groups, setGroups] = useState<GroupRow[]>([]);
  const [connections, setConnections] = useState<ConnectionRow[]>([]);
  const [bots, setBots] = useState<BotRow[]>([]);
  const [transactions, setTransactions] = useState<TxRow[]>([]);
  const [paymentProfile, setPaymentProfile] = useState<PaymentProfile | null>(null);
  const [bankCards, setBankCards] = useState<BankCardRow[]>([]);
  const [audits, setAudits] = useState<AuditRow[]>([]);
  const [twoFactor, setTwoFactor] = useState<TwoFactor | null>(null);

  const [adminsPage, setAdminsPage] = useState<PageResult<AdminRow>>({ items: [], total: 0, page: 1, page_size: 25, pages: 0 });
  const [clientsPage, setClientsPage] = useState<PageResult<ClientRow>>({ items: [], total: 0, page: 1, page_size: 25, pages: 0 });
  const [paymentsPage, setPaymentsPage] = useState<PageResult<PaymentRow>>({ items: [], total: 0, page: 1, page_size: 25, pages: 0 });
  const [ordersPage, setOrdersPage] = useState<PageResult<OrderRow>>({ items: [], total: 0, page: 1, page_size: 25, pages: 0 });
  const [customersPage, setCustomersPage] = useState<PageResult<CustomerRow>>({ items: [], total: 0, page: 1, page_size: 25, pages: 0 });

  const [adminSearch, setAdminSearch] = useState("");
  const [adminStatus, setAdminStatus] = useState("");
  const [adminSort, setAdminSort] = useState("newest");
  const [adminPickerSearch, setAdminPickerSearch] = useState("");
  const [adminOptions, setAdminOptions] = useState<AdminRow[]>([]);
  const [clientSearch, setClientSearch] = useState("");
  const [clientStatus, setClientStatus] = useState("");
  const [clientAdminFilter, setClientAdminFilter] = useState("");
  const [clientSort, setClientSort] = useState("newest");
  const [paymentStatus, setPaymentStatus] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("");
  const [paymentSearch, setPaymentSearch] = useState("");
  const [paymentDate, setPaymentDate] = useState("");
  const [commerceTab, setCommerceTab] = useState<"payments" | "orders" | "customers">("payments");
  const [customerSearch, setCustomerSearch] = useState("");

  const [adminForm, setAdminForm] = useState({
    username: "",
    display_name: "",
    password: "",
    telegram_id: "",
    initial_balance_toman: "0",
  });
  const [clientForm, setClientForm] = useState({
    username: "",
    admin_id: "",
    plan_id: "",
    quota_gib: "50",
    duration_days: "30",
    hwid_limit: "1",
  });
  const [planForm, setPlanForm] = useState({
    name: "",
    group_id: "",
    base_price_per_gib_toman: "",
    min_quota_gib: "1",
    max_quota_gib: "",
    max_duration_days: "365",
    default_hwid_limit: "1",
  });
  const [connectionForm, setConnectionForm] = useState({
    name: "",
    base_url: "",
    api_token: "",
  });
  const [botForm, setBotForm] = useState({
    name: "",
    token: "",
    admin_id: "",
    customer_wallet_enabled: true,
    card_to_card_enabled: true,
    gateway_enabled: false,
  });
  const [cardForm, setCardForm] = useState({
    title: "کارت اصلی",
    card_number: "",
    card_holder_name: "",
    instructions: "",
    is_default: true,
  });
  const [gatewayMerchant, setGatewayMerchant] = useState("");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [accent, setAccent] = useState<"cyan" | "violet" | "emerald" | "orange">("cyan");
  const [adminAssignments, setAdminAssignments] = useState<AdminPlanAssignment[]>([]);
  const [clientPlanOptions, setClientPlanOptions] = useState<PlanRow[]>([]);
  const [backupFile, setBackupFile] = useState<File | null>(null);
  const [walletTopup, setWalletTopup] = useState("100000");
  const [walletReceipt, setWalletReceipt] = useState<File | null>(null);

  const activeNav = navigation.find((n) => n.key === section) || navigation[0];
  const visibleNav = navigation.filter((n) => user.role === "owner" ? n.owner : n.admin);
  const unread = notifications.filter((n) => !n.is_read).length;

  const selectedAdmin = useMemo(
    () => adminsPage.items.find((x) => x.id === selectedId) || null,
    [adminsPage.items, selectedId],
  );
  const selectedClient = useMemo(
    () => clientsPage.items.find((x) => x.id === selectedId) || null,
    [clientsPage.items, selectedId],
  );
  const selectedPlan = useMemo(
    () => plans.find((x) => x.id === selectedId) || null,
    [plans, selectedId],
  );
  const selectedConnection = useMemo(
    () => connections.find((x) => x.id === selectedId) || null,
    [connections, selectedId],
  );
  const selectedBot = useMemo(
    () => bots.find((x) => x.id === selectedId) || null,
    [bots, selectedId],
  );

  function qs(params: Record<string, string | number | null | undefined>) {
    const q = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && String(value) !== "") q.set(key, String(value));
    }
    return q.toString();
  }

  async function safe<T>(fn: () => Promise<T>): Promise<T | null> {
    try {
      return await fn();
    } catch (e) {
      const message = e instanceof Error ? e.message : "خطا در ارتباط با سرور";
      if (message === "session_expired") onSessionExpired();
      else setError(message);
      return null;
    }
  }

  async function run(fn: () => Promise<unknown>, message = "انجام شد") {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await fn();
      setSuccess(message);
      await reloadSection();
      setActionDialog(null);
      setModal(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "عملیات ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  async function loadGlobal() {
    const data = await Promise.all([
      safe(() => authApi<Summary>("/api/v1/dashboard/summary")),
      safe(() => authApi<NotificationRow[]>("/api/v1/notifications?limit=20")),
      safe(() => authApi<Financial>("/api/v1/reports/financial")),
    ]);
    if (data[0]) setSummary(data[0]);
    if (data[1]) setNotifications(data[1]);
    if (data[2]) setFinancial(data[2]);

    if (user.role === "owner") {
      const connectionRows = await safe(() => authApi<ConnectionRow[]>("/api/v1/connections"));
      if (connectionRows) setConnections(connectionRows);
    }
  }

  async function loadAdmins(page = adminsPage.page) {
    if (user.role !== "owner") return;
    const data = await safe(() => authApi<PageResult<AdminRow>>(
      `/api/v1/directory/admins?${qs({
        q: adminSearch,
        status_filter: adminStatus,
        sort: adminSort,
        page,
        page_size: 25,
      })}`
    ));
    if (data) setAdminsPage(data);
  }

  async function loadClients(page = clientsPage.page) {
    const data = await safe(() => authApi<PageResult<ClientRow>>(
      `/api/v1/directory/clients?${qs({
        q: clientSearch,
        status_filter: clientStatus,
        admin_id: user.role === "owner" ? clientAdminFilter : "",
        sort: clientSort,
        page,
        page_size: 25,
      })}`
    ));
    if (data) setClientsPage(data);
  }

  async function loadPlans() {
    const data = await Promise.all([
      safe(() => authApi<PlanRow[]>("/api/v1/plans")),
      safe(() => authApi<GroupRow[]>("/api/v1/groups")),
    ]);
    if (data[0]) setPlans(data[0]);
    if (data[1]) setGroups(data[1]);
  }

  async function loadWallet() {
    const data = await safe(() => authApi<TxRow[]>("/api/v1/wallet/transactions?limit=100"));
    if (data) setTransactions(data);
  }

  async function loadPayments(page = paymentsPage.page) {
    const data = await safe(() => authApi<PageResult<PaymentRow>>(
      `/api/v1/directory/payments?${qs({
        q: paymentSearch,
        status_filter: paymentStatus,
        method: paymentMethod,
        date_filter: paymentDate,
        page,
        page_size: 25,
      })}`
    ));
    if (data) setPaymentsPage(data);
  }

  async function loadOrders(page = ordersPage.page) {
    const data = await safe(() => authApi<PageResult<OrderRow>>(
      `/api/v1/directory/orders?${qs({ page, page_size: 25 })}`
    ));
    if (data) setOrdersPage(data);
  }

  async function loadCustomers(page = customersPage.page) {
    const data = await safe(() => authApi<PageResult<CustomerRow>>(
      `/api/v1/directory/customers?${qs({ q: customerSearch, page, page_size: 25 })}`
    ));
    if (data) setCustomersPage(data);
  }

  async function loadBots() {
    const data = await safe(() => authApi<BotRow[]>("/api/v1/bots"));
    if (data) setBots(data);
  }

  async function loadConnections() {
    if (user.role !== "owner") return;
    const data = await safe(() => authApi<ConnectionRow[]>("/api/v1/connections"));
    if (data) setConnections(data);
  }

  async function loadSettings() {
    const data = await Promise.all([
      safe(() => authApi<PaymentProfile>("/api/v1/payment-profile")),
      safe(() => authApi<BankCardRow[]>("/api/v1/bank-cards")),
      safe(() => authApi<TwoFactor>("/api/v1/security/2fa/status")),
    ]);
    if (data[0]) setPaymentProfile(data[0]);
    if (data[1]) setBankCards(data[1]);
    if (data[2]) setTwoFactor(data[2]);
  }

  async function loadReports() {
    await loadGlobal();
    if (user.role === "owner") {
      const data = await safe(() => authApi<AuditRow[]>("/api/v1/audit-logs?limit=100"));
      if (data) setAudits(data);
    }
  }

  async function reloadSection() {
    await loadGlobal();
    if (section === "admins") await loadAdmins();
    if (section === "clients") {
      if (user.role === "owner") await searchAdminOptions("");
      await loadClients();
    }
    if (section === "plans") await loadPlans();
    if (section === "wallet") await loadWallet();
    if (section === "commerce") {
      if (commerceTab === "payments") await loadPayments();
      if (commerceTab === "orders") await loadOrders();
      if (commerceTab === "customers") await loadCustomers();
    }
    if (section === "bots") await loadBots();
    if (section === "pasarguard") await loadConnections();
    if (section === "reports") await loadReports();
    if (section === "settings") await loadSettings();
  }

  useEffect(() => {
    const savedTheme = (localStorage.getItem("primevpn_theme") as "dark" | "light" | null) || "dark";
    const savedAccent = (localStorage.getItem("primevpn_accent") as typeof accent | null) || "cyan";
    setTheme(savedTheme);
    setAccent(savedAccent);
    document.documentElement.dataset.theme = savedTheme;
    document.documentElement.dataset.accent = savedAccent;
    loadGlobal();
  }, []);

  useEffect(() => {
    reloadSection();
  }, [section, commerceTab]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.accent = accent;
    localStorage.setItem("primevpn_theme", theme);
    localStorage.setItem("primevpn_accent", accent);
  }, [theme, accent]);

  async function signOut() {
    await logout();
    onSessionExpired();
  }

  function go(key: string) {
    setSection(key);
    setDrawer(false);
    setError("");
    setSuccess("");
  }

  async function searchAdminOptions(query = adminPickerSearch) {
    if (user.role !== "owner") return;
    const data = await safe(() => authApi<PageResult<AdminRow>>(
      `/api/v1/directory/admins?${qs({ q: query, status_filter: "active", page: 1, page_size: 50 })}`
    ));
    if (data) setAdminOptions(data.items);
  }

  async function contextualCreate() {
    if (section === "admins") setModal("admin-create");
    else if (section === "clients") {
      if (!plans.length) await loadPlans();
      if (user.role === "owner") {
        await searchAdminOptions("");
        setClientPlanOptions([]);
        setClientForm((old) => ({ ...old, admin_id: "", plan_id: "" }));
      }
      setModal("client-create");
    }
    else if (section === "plans" && user.role === "owner") {
      if (!groups.length) await loadPlans();
      setModal("plan-create");
    }
    else if (section === "bots") {
      if (user.role === "owner") await searchAdminOptions("");
      setModal("bot-create");
    }
    else if (section === "pasarguard" && user.role === "owner") setModal("connection-create");
  }

  const canCreate = ["admins", "clients", "plans", "bots", "pasarguard"].includes(section) &&
    !(user.role === "admin" && ["admins", "plans", "pasarguard"].includes(section));

  async function createAdmin(e: FormEvent) {
    e.preventDefault();
    await run(() => authApi("/api/v1/admins", {
      method: "POST",
      body: JSON.stringify({
        username: adminForm.username,
        display_name: adminForm.display_name || null,
        password: adminForm.password,
        telegram_id: adminForm.telegram_id ? Number(adminForm.telegram_id) : null,
        initial_balance_toman: Number(adminForm.initial_balance_toman || 0),
      }),
    }), "نماینده ساخته شد");
    setAdminForm({ username: "", display_name: "", password: "", telegram_id: "", initial_balance_toman: "0" });
  }

  async function createClient(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (user.role === "owner" && !clientForm.admin_id) {
      setError("ابتدا نماینده را انتخاب کنید.");
      return;
    }
    if (!clientForm.plan_id) {
      setError(
        user.role === "owner"
          ? "برای این نماینده یک پلن تخصیص‌داده‌شده انتخاب کنید."
          : "یک پلن فعال انتخاب کنید."
      );
      return;
    }
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
    }), "پلن پایه ساخته شد");
  }

  async function createConnection(e: FormEvent) {
    e.preventDefault();
    await run(() => authApi("/api/v1/connections", {
      method: "POST",
      body: JSON.stringify(connectionForm),
    }), "PasarGuard تست و اضافه شد");
    setConnectionForm({ name: "", base_url: "", api_token: "" });
  }

  async function createBot(e: FormEvent) {
    e.preventDefault();
    await run(() => authApi("/api/v1/bots", {
      method: "POST",
      body: JSON.stringify({
        ...botForm,
        admin_id: user.role === "owner" ? botForm.admin_id : null,
      }),
    }), "ربات ثبت و فعال شد");
    setBotForm({ name: "", token: "", admin_id: "", customer_wallet_enabled: true, card_to_card_enabled: true, gateway_enabled: false });
  }

  async function createCard(e: FormEvent) {
    e.preventDefault();
    await run(() => authApi("/api/v1/bank-cards", {
      method: "POST",
      body: JSON.stringify({
        ...cardForm,
        enabled: true,
      }),
    }), "کارت بانکی ذخیره شد");
    setCardForm({ title: "کارت اصلی", card_number: "", card_holder_name: "", instructions: "", is_default: bankCards.length === 0 });
  }

  async function openAdminManage(admin: AdminRow) {
    setSelectedId(admin.id);
    const data = await safe(() => authApi<AdminPlanAssignment[]>(`/api/v1/admins/${admin.id}/plans`));
    setAdminAssignments(data || []);
    setModal("admin-manage");
  }

  async function chooseClientAdmin(adminId: string) {
    setClientForm((old) => ({ ...old, admin_id: adminId, plan_id: "" }));
    if (!adminId) {
      setClientPlanOptions([]);
      return;
    }
    const data = await safe(() => authApi<AdminPlanAssignment[]>(`/api/v1/admins/${adminId}/plans`));
    if (!data) return;
    const enabled = data.filter((x) => x.enabled);
    setClientPlanOptions(enabled.map((x) => ({
      id: x.plan_id,
      name: x.name,
      group_id: "",
      enabled: x.enabled,
      base_price_per_gib_toman: x.base_price_per_gib_toman,
      retail_price_per_gib_toman: x.retail_price_per_gib_toman,
    })));
  }

  async function openBotManage(bot: BotRow) {
    setSelectedId(bot.id);
    setModal("bot-manage");
  }

  async function reviewPayment(payment: PaymentRow, approved: boolean) {
    await run(() => authApi(`/api/v1/payments/${payment.id}/review`, {
      method: "POST",
      body: JSON.stringify({ approved, note: approved ? "Approved from panel" : "Rejected from panel" }),
    }), approved ? "پرداخت تأیید شد" : "پرداخت رد شد");
  }

  async function viewReceipt(id: string) {
    const blob = await safe(() => authBlob(`/api/v1/payments/${id}/receipt`));
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener,noreferrer");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  async function exportBackup() {
    const blob = await safe(() => authBlob("/api/v1/backups/export"));
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `primevpn-${new Date().toISOString().slice(0, 10)}.pvbackup`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  function openActionDialog(config: ActionDialogState, defaults: Record<string, string> = {}) {
    const values: Record<string, string> = {};
    for (const field of config.fields) values[field.key] = defaults[field.key] || "";
    setActionValues(values);
    setError("");
    setActionDialog(config);
  }

  async function submitActionDialog(e: FormEvent) {
    e.preventDefault();
    if (!actionDialog) return;

    for (const field of actionDialog.fields) {
      if (field.required && !String(actionValues[field.key] || "").trim()) {
        setError(`${field.label} الزامی است.`);
        return;
      }
    }

    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await actionDialog.onSubmit(actionValues);
      setSuccess(actionDialog.successMessage);
      await reloadSection();
      setActionDialog(null);
      setModal(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "عملیات ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  function openConfirmAction({
    title,
    description,
    submitLabel,
    successMessage,
    action,
  }: {
    title: string;
    description: string;
    submitLabel: string;
    successMessage: string;
    action: () => Promise<unknown>;
  }) {
    openActionDialog({
      title,
      description,
      fields: [],
      submitLabel,
      destructive: true,
      successMessage,
      onSubmit: action,
    });
  }

  function openAdminWalletTopup(admin: AdminRow) {
    openActionDialog({
      title: "شارژ کیف پول نماینده",
      description: `افزایش موجودی کیف پول ${admin.display_name || admin.username}`,
      fields: [
        { key: "amount", label: "مبلغ شارژ (تومان)", type: "number", placeholder: "مثلاً ۵۰۰۰۰", required: true },
      ],
      submitLabel: "شارژ کیف پول",
      successMessage: "کیف پول شارژ شد",
      onSubmit: (values) => authApi(`/api/v1/admins/${admin.id}/wallet/topup`, {
        method: "POST",
        body: JSON.stringify({ amount_toman: Number(values.amount), note: "Owner top-up" }),
      }),
    });
  }

  function openAdminEdit(admin: AdminRow) {
    openActionDialog({
      title: "ویرایش مشخصات نماینده",
      description: `ویرایش ${admin.display_name || admin.username}`,
      fields: [
        { key: "display_name", label: "نام نمایشی", type: "text" },
        { key: "telegram_id", label: "Telegram ID", type: "number" },
        { key: "threshold", label: "حد هشدار کیف پول", type: "number" },
        { key: "debt", label: "سقف بدهی", type: "number" },
        { key: "password", label: "رمز جدید", type: "password", placeholder: "خالی = بدون تغییر" },
      ],
      submitLabel: "ذخیره تغییرات",
      successMessage: "نماینده ویرایش شد",
      onSubmit: (values) => authApi(`/api/v1/admins/${admin.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          display_name: values.display_name || null,
          telegram_id: values.telegram_id ? Number(values.telegram_id) : null,
          low_balance_threshold_toman: Number(values.threshold || 0),
          debt_limit_toman: Number(values.debt || 0),
          password: values.password || null,
        }),
      }),
    }, {
      display_name: admin.display_name || "",
      telegram_id: admin.telegram_id ? String(admin.telegram_id) : "",
      threshold: admin.low_balance_threshold_toman || "0",
      debt: admin.debt_limit_toman || "0",
      password: "",
    });
  }

  function openClientEdit(client: ClientRow) {
    openActionDialog({
      title: "ویرایش کلاینت",
      description: client.username,
      fields: [
        { key: "quota", label: "حجم جدید GB", type: "number", placeholder: "خالی = تغییر نکند" },
        { key: "days", label: "تمدید از امروز (روز)", type: "number", placeholder: "خالی = تغییر نکند" },
        { key: "hwid", label: "تعداد دستگاه", type: "number", placeholder: "خالی = تغییر نکند" },
      ],
      submitLabel: "ذخیره تغییرات",
      successMessage: "کلاینت ویرایش شد",
      onSubmit: (values) => authApi(`/api/v1/clients/${client.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          quota_gib: values.quota ? Number(values.quota) : null,
          duration_days_from_now: values.days ? Number(values.days) : null,
          hwid_limit: values.hwid ? Number(values.hwid) : null,
        }),
      }),
    });
  }

  function openOwnerPlanEdit(plan: PlanRow) {
    openActionDialog({
      title: "ویرایش پلن",
      description: plan.name,
      fields: [
        { key: "name", label: "نام پلن", type: "text", required: true },
        { key: "price", label: "قیمت پایه هر GB", type: "number", required: true },
      ],
      submitLabel: "ذخیره پلن",
      successMessage: "پلن ویرایش شد",
      onSubmit: (values) => authApi(`/api/v1/plans/${plan.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: values.name, base_price_per_gib_toman: Number(values.price) }),
      }),
    }, {
      name: plan.name,
      price: String(plan.base_price_per_gib_toman || ""),
    });
  }

  function openRetailPlanEdit(plan: PlanRow) {
    openActionDialog({
      title: "قیمت فروش پلن",
      description: plan.name,
      fields: [
        { key: "price", label: "قیمت فروش هر GB", type: "number", required: true },
      ],
      submitLabel: "ذخیره قیمت",
      successMessage: "قیمت فروش ذخیره شد",
      onSubmit: (values) => authApi(`/api/v1/my-plans/${plan.id}/retail-price`, {
        method: "PATCH",
        body: JSON.stringify({ retail_price_per_gib_toman: Number(values.price) }),
      }),
    }, {
      price: String(plan.retail_price_per_gib_toman || ""),
    });
  }

  function openConnectionEdit(connection: ConnectionRow) {
    openActionDialog({
      title: "ویرایش اتصال PasarGuard",
      description: connection.name,
      fields: [
        { key: "name", label: "نام اتصال", type: "text", required: true },
        { key: "url", label: "Panel URL", type: "url", required: true },
        { key: "token", label: "API Token جدید", type: "password", placeholder: "خالی = بدون تغییر" },
      ],
      submitLabel: "ذخیره اتصال",
      successMessage: "اتصال ویرایش شد",
      onSubmit: (values) => authApi(`/api/v1/connections/${connection.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: values.name,
          base_url: values.url,
          api_token: values.token || null,
          enabled: true,
        }),
      }),
    }, {
      name: connection.name,
      url: connection.base_url,
      token: "",
    });
  }

  function openBotEdit(bot: BotRow) {
    openActionDialog({
      title: "ویرایش ربات فروش",
      description: bot.username ? `@${bot.username}` : bot.name,
      fields: [
        { key: "name", label: "نام ربات", type: "text", required: true },
        { key: "token", label: "Bot Token جدید", type: "password", placeholder: "خالی = بدون تغییر" },
      ],
      submitLabel: "ذخیره ربات",
      successMessage: "ربات ویرایش شد",
      onSubmit: (values) => authApi(`/api/v1/bots/${bot.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: values.name, token: values.token || null }),
      }),
    }, {
      name: bot.name,
      token: "",
    });
  }

  async function openEnable2FA() {
    setBusy(true);
    setError("");
    try {
      const setup = await authApi<{ secret: string; recovery_codes: string[] }>("/api/v1/security/2fa/setup", { method: "POST" });
      openActionDialog({
        title: "فعال‌سازی 2FA",
        description: "Secret و Recovery Codeها را قبل از ادامه در جای امن ذخیره کنید.",
        notice: `Secret: ${setup.secret}\n\nRecovery Codes:\n${setup.recovery_codes.join("   ")}`,
        fields: [
          { key: "code", label: "کد ۶ رقمی Authenticator", type: "number", required: true },
        ],
        submitLabel: "فعال‌سازی 2FA",
        successMessage: "2FA فعال شد",
        onSubmit: (values) => authApi("/api/v1/security/2fa/enable", {
          method: "POST",
          body: JSON.stringify({ code: values.code }),
        }),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "ساخت تنظیمات 2FA ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  function openDisable2FA() {
    openActionDialog({
      title: "غیرفعال‌کردن 2FA",
      description: "برای تأیید، کد فعلی Authenticator را وارد کنید.",
      fields: [
        { key: "code", label: "کد Authenticator", type: "number", required: true },
      ],
      submitLabel: "غیرفعال‌کردن 2FA",
      destructive: true,
      successMessage: "2FA غیرفعال شد",
      onSubmit: (values) => authApi("/api/v1/security/2fa/disable", {
        method: "POST",
        body: JSON.stringify({ code: values.code }),
      }),
    });
  }

  async function restoreBackup() {
    if (!backupFile) {
      setError("فایل Backup را انتخاب کنید");
      return;
    }
    openActionDialog({
      title: "بازیابی Backup",
      description: "Restore به‌صورت Merge انجام می‌شود و داده فعلی حذف نمی‌شود.",
      fields: [],
      submitLabel: "شروع بازیابی",
      destructive: true,
      successMessage: "Backup بازیابی شد",
      onSubmit: async () => {
        const fd = new FormData();
        fd.append("backup", backupFile);
        return authApi("/api/v1/backups/restore", { method: "POST", body: fd });
      },
    });
  }

  function renderDashboard() {
    const pasarGuardOnline = user.role === "admin" || connections.some((item) => item.enabled && !item.last_error);

    const metrics = [
      {
        label: "کاربران",
        value: summary?.clients || 0,
        note: "تعداد کل کاربران",
        icon: Users,
        tone: "violet",
      },
      {
        label: "اشتراک‌های فعال",
        value: summary?.active_clients || 0,
        note: "کاربران فعال سرویس",
        icon: ShieldCheck,
        tone: "blue",
      },
      {
        label: "مصرف Lifetime",
        value: gib(summary?.lifetime_usage_bytes),
        note: "مجموع ترافیک مصرفی",
        icon: Database,
        tone: "purple",
      },
      {
        label: "پرداخت امروز",
        value: money(summary?.today_paid_toman || 0),
        note: "جمع پرداخت‌های امروز",
        icon: Wallet,
        tone: "cyan",
      },
    ];

    const services = [
      { label: "API", icon: Code2, ok: true },
      { label: "Billing Worker", icon: Settings, ok: true },
      { label: "Telegram Worker", icon: Send, ok: true },
      { label: "PostgreSQL", icon: Database, ok: true },
      { label: "Redis", icon: Boxes, ok: true },
      { label: "PasarGuard", icon: ShieldCheck, ok: pasarGuardOnline },
    ];

    const financeCards = [
      { label: "موجودی", value: money(summary?.wallet_balance_toman), icon: WalletCards, tone: "blue" },
      { label: "فروش امروز", value: money(summary?.today_paid_toman || 0), icon: CircleDollarSign, tone: "violet" },
      { label: "سفارشات جدید", value: summary?.today_orders || 0, icon: Boxes, tone: "cyan" },
      { label: "هزینه مصرف", value: money(financial?.actual_usage_cost_toman), icon: Activity, tone: "purple" },
    ];

    return (
      <div className="primeDashboard">
        <section className="primeDashMetrics">
          {metrics.map((item) => {
            const Icon = item.icon;
            return (
              <article className={`primeDashMetric ${item.tone}`} key={item.label}>
                <div className="primeDashMetricIcon"><Icon size={25} /></div>
                <div className="primeDashMetricBody">
                  <span>{item.label}</span>
                  <strong>{String(item.value)}</strong>
                  <small>{item.note}</small>
                </div>
                <i className="primeDashWave" />
              </article>
            );
          })}
        </section>

        <section className="primeDashPanel primeDashOps">
          <div className="primeDashPanelHead">
            <div className="primeDashTitleIcon violet"><Settings size={23} /></div>
            <div>
              <strong>مرکز عملیات</strong>
              <span>پایش وضعیت سرویس‌ها و زیرساخت‌ها</span>
            </div>
            <div className="primeDashLive"><i />LIVE</div>
          </div>

          <div className="primeDashServiceList">
            {services.map((service) => {
              const Icon = service.icon;
              return (
                <div className="primeDashService" key={service.label}>
                  <div className="primeDashServiceName"><Icon size={18} /><span>{service.label}</span></div>
                  <div className={service.ok ? "primeDashState online" : "primeDashState warning"}>
                    <i />{service.ok ? "آنلاین" : "هشدار"}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="primeDashPanel primeDashFinancePanel">
          <div className="primeDashPanelHead">
            <div className="primeDashTitleIcon violet"><WalletCards size={22} /></div>
            <div>
              <strong>خلاصه مالی</strong>
              <span>نمای کلی وضعیت مالی و پرداخت‌ها</span>
            </div>
          </div>

          <div className="primeDashFinanceGrid">
            {financeCards.map((item) => {
              const Icon = item.icon;
              return (
                <article className={`primeDashFinanceCard ${item.tone}`} key={item.label}>
                  <div className="primeDashFinanceIcon"><Icon size={21} /></div>
                  <div><span>{item.label}</span><strong>{String(item.value)}</strong></div>
                  <i className="primeDashWave" />
                </article>
              );
            })}
          </div>
        </section>

        <section className="primeDashPanel primeDashNotice" id="prime-dashboard-notifications">
          <div className="primeDashPanelHead">
            <div className="primeDashTitleIcon violet"><Bell size={22} /></div>
            <div>
              <strong>اعلان‌ها</strong>
              <span>جدیدترین اطلاعیه‌ها و وضعیت سیستم</span>
            </div>
          </div>

          {notifications.length ? (
            <div className="primeDashNoticeList">
              {notifications.slice(0, 5).map((notification) => (
                <button
                  key={notification.id}
                  onClick={() => !notification.is_read && run(
                    () => authApi(`/api/v1/notifications/${notification.id}/read`, { method: "POST" }),
                    "اعلان خوانده شد",
                  )}
                >
                  <Bell size={16} />
                  <div><strong>{notification.title}</strong><span>{notification.message}</span></div>
                  {!notification.is_read && <i />}
                </button>
              ))}
            </div>
          ) : (
            <div className="primeDashEmptyNotice">
              <span><Bell size={25} /></span>
              <p>اعلان جدیدی ندارید</p>
            </div>
          )}
        </section>
      </div>
    );
  }

  function renderAdmins() {
    return (
      <div className="primeAdminsPage">
        <section className="primeAdminDirectory">
          <div className="primeAdminSearchBox">
            <button onClick={() => loadAdmins(1)} aria-label="جستجو"><Search size={25} /></button>
            <input
              value={adminSearch}
              onChange={(e) => setAdminSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadAdmins(1)}
              placeholder="جستجوی نام کاربری یا نام نماینده"
            />
            <i className="primeAdminSearchWave" />
          </div>

          <div className="primeAdminFilters">
            <button className="primeAdminFilterButton" onClick={() => loadAdmins(1)} aria-label="اعمال فیلتر">
              <SlidersHorizontal size={24} />
            </button>
            <label>
              <PrimeSelect
                value={adminSort}
                onChange={setAdminSort}
                options={[
                  { value: "newest", label: "جدیدترین" },
                  { value: "oldest", label: "قدیمی‌ترین" },
                ]}
              />
              <ChevronLeft size={18} />
            </label>
            <label>
              <PrimeSelect
                value={adminStatus}
                onChange={setAdminStatus}
                options={[
                  { value: "", label: "همه وضعیت‌ها" },
                  { value: "active", label: "فعال" },
                  { value: "disabled", label: "غیرفعال" },
                ]}
              />
              <ChevronLeft size={18} />
            </label>
          </div>

          <div className="primeAdminTable">
            <div className="primeAdminTableHead">
              <span>نماینده</span>
              <span>کلاینت</span>
              <span>پلن‌ها</span>
              <span>وضعیت</span>
            </div>

            <div className="primeAdminTableBody">
              {adminsPage.items.map((admin) => (
                <button className="primeAdminRow" key={admin.id} onClick={() => openAdminManage(admin)}>
                  <div>
                    <strong>{admin.display_name || admin.username}</strong>
                    <small>@{admin.username}</small>
                  </div>
                  <span>{admin.client_count.toLocaleString("fa-IR")}</span>
                  <span>{Number(admin.plan_count || 0).toLocaleString("fa-IR")}</span>
                  <span className={admin.status === "active" ? "primeAdminStatus active" : "primeAdminStatus disabled"}>
                    {admin.status === "active" ? "فعال" : "غیرفعال"}
                  </span>
                </button>
              ))}

              {!adminsPage.items.length && (
                <div className="primeAdminEmpty">
                  <span><Users size={39} /></span>
                  <strong>نماینده‌ای پیدا نشد</strong>
                </div>
              )}
            </div>

            <div className="primeAdminPager">
              <span>{adminsPage.total.toLocaleString("fa-IR")} ردیف</span>
              <div>
                <button disabled={adminsPage.page <= 1} onClick={() => loadAdmins(adminsPage.page - 1)}>
                  <ChevronRight size={21} />
                </button>
                <b>{adminsPage.page.toLocaleString("fa-IR")} / {Math.max(adminsPage.pages, 1).toLocaleString("fa-IR")}</b>
                <button disabled={adminsPage.page >= adminsPage.pages} onClick={() => loadAdmins(adminsPage.page + 1)}>
                  <ChevronLeft size={21} />
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>
    );
  }

  function renderClients() {
    return (
      <div className="primeClientsPage">
        <section className="primeClientDirectory">
          <div className="primeClientSearchBox">
            <button onClick={() => loadClients(1)} aria-label="جستجو"><Search size={25} /></button>
            <input
              value={clientSearch}
              onChange={(e) => setClientSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadClients(1)}
              placeholder="جستجو بر اساس نام کاربری"
            />
            <i className="primeClientSearchWave" />
          </div>

          <div className="primeClientFilters">
            <button className="primeClientFilterButton" onClick={() => loadClients(1)} aria-label="اعمال فیلتر">
              <SlidersHorizontal size={24} />
            </button>

            <label>
              <PrimeSelect
                value={clientSort}
                onChange={setClientSort}
                options={[
                  { value: "newest", label: "جدیدترین" },
                  { value: "oldest", label: "قدیمی‌ترین" },
                ]}
              />
              <ChevronLeft size={18} />
            </label>

            {user.role === "owner" && (
              <label>
                <PrimeSelect
                  value={clientAdminFilter}
                  onChange={setClientAdminFilter}
                  placeholder="نماینده"
                  options={[
                    { value: "", label: "همه نماینده‌ها" },
                    ...adminOptions.map((admin) => ({ value: admin.id, label: admin.display_name || admin.username })),
                  ]}
                />
                <ChevronLeft size={18} />
              </label>
            )}

            <label>
              <PrimeSelect
                value={clientStatus}
                onChange={setClientStatus}
                options={[
                  { value: "", label: "همه وضعیت‌ها" },
                  { value: "active", label: "فعال" },
                  { value: "disabled", label: "غیرفعال" },
                  { value: "error", label: "خطا" },
                ]}
              />
              <ChevronLeft size={18} />
            </label>
          </div>

          <div className="primeClientTable">
            <div className="primeClientTableHead">
              <span>کلاینت</span>
              <span>نماینده</span>
              <span>سرور</span>
              <span>سهم</span>
              <span>ایجاد</span>
            </div>

            <div className="primeClientTableBody">
              {clientsPage.items.map((client) => (
                <button
                  className="primeClientRow"
                  key={client.id}
                  onClick={() => { setSelectedId(client.id); setModal("client-manage"); }}
                >
                  <div><strong>{client.username}</strong><small>{statusFa(client.status)}</small></div>
                  <span>{client.admin_username || "—"}</span>
                  <span>{client.connection_name || client.group_name || "—"}</span>
                  <span>{client.quota_bytes ? gib(client.quota_bytes) : "∞"}</span>
                  <span>{dt(client.created_at)}</span>
                </button>
              ))}

              {!clientsPage.items.length && (
                <div className="primeClientEmpty">
                  <span><Users size={39} /></span>
                  <strong>کلاینتی پیدا نشد</strong>
                </div>
              )}
            </div>

            <div className="primeClientPager">
              <span>{clientsPage.total.toLocaleString("fa-IR")} ردیف</span>
              <div>
                <button disabled={clientsPage.page <= 1} onClick={() => loadClients(clientsPage.page - 1)}>
                  <ChevronRight size={21} />
                </button>
                <b>{clientsPage.page.toLocaleString("fa-IR")} / {Math.max(clientsPage.pages, 1).toLocaleString("fa-IR")}</b>
                <button disabled={clientsPage.page >= clientsPage.pages} onClick={() => loadClients(clientsPage.page + 1)}>
                  <ChevronLeft size={21} />
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>
    );
  }

  function renderPlans() {
    return (
      <div className="primePlansPage">
        <section className="primePlanSection">
          <div className="primePlanSectionHead">
            <div className="primePlanSectionIcon"><Database size={27} /></div>
            <div><strong>پلن‌ها</strong><span>پلن‌های مالک به‌صورت خودکار برای همه نمایندگان فعال می‌شوند</span></div>
          </div>

          {plans.length ? (
            <div className="primePlanCards">
              {plans.map((plan) => (
                <button
                  key={plan.id}
                  className="primePlanCard"
                  onClick={async () => {
                    setSelectedId(plan.id);
                    if (user.role === "owner") await searchAdminOptions("");
                    setModal("plan-manage");
                  }}
                >
                  <div><strong>{plan.name}</strong><span className={plan.enabled === false ? "off" : "on"}>{plan.enabled === false ? "خاموش" : "فعال"}</span></div>
                  <b>{money(plan.retail_price_per_gib_toman || plan.base_price_per_gib_toman || plan.cost_per_gib_toman)} / GB</b>
                  <small>حداکثر {plan.max_quota_gib || "∞"} GB · {plan.max_duration_days || "∞"} روز</small>
                </button>
              ))}
            </div>
          ) : (
            <div className="primePlanEmpty">
              <span><CreditCard size={43} /></span>
              <strong>پلنی تعریف نشده</strong>
              <p>هنوز هیچ پلنی ثبت نشده است.<br />برای شروع روی دکمه «افزودن» کلیک کنید.</p>
            </div>
          )}
        </section>

        <section className="primePlanInfo primePlanGroups">
          <div className="primePlanSectionHead">
            <div className="primePlanSectionIcon purple"><Users size={27} /></div>
            <div><strong>گروه‌ها</strong><span>مدیریت گروه‌ها و هماهنگی با PasarGuard از طریق همگام‌سازی</span></div>
          </div>
          <div className="primePlanInfoBody">
            <div className="primePlanInfoVisual"><Users size={54} /></div>
            <div>
              <strong>گروه‌های کاربری را ایجاد و مدیریت کنید.</strong>
              <p>اطلاعات گروه‌ها با سرویس PasarGuard همگام‌سازی می‌شود.</p>
              {groups.length > 0 && (
                <div className="primePlanGroupChips">
                  {groups.slice(0, 8).map((group) => <span key={group.id}>{group.name}</span>)}
                </div>
              )}
            </div>
          </div>
        </section>

        <section className="primePlanInfo primePlanRules">
          <div className="primePlanSectionHead">
            <div className="primePlanSectionIcon pink"><Settings size={27} /></div>
            <div><strong>قانون فروش</strong><span>قوانین پیش‌فرض فروش و محدودیت‌ها</span></div>
          </div>
          <div className="primePlanInfoBody">
            <div className="primePlanInfoVisual"><Settings size={52} /></div>
            <div>
              <p>شما می‌توانید محدودیت‌ها و قوانین پیش‌فرض فروش را تنظیم کنید.</p>
              <p>قوانین فروش، قیمت پایه و محدودیت‌های هر پلن در این بخش مدیریت می‌شوند.</p>
            </div>
          </div>
        </section>
      </div>
    );
  }

  function renderWallet() {
    return (
      <div className="primeWalletPage">
        <section className="primeWalletBalance">
          <div className="primeWalletBalanceIcon"><WalletCards size={38} /></div>
          <div>
            <span>موجودی کل</span>
            <strong>{money(summary?.wallet_balance_toman)}</strong>
            <small>مجموع موجودی کیف پول شما</small>
          </div>
          <i />
        </section>

        {user.role === "admin" && (
          <section className="primeWalletTopup">
            <div className="primeWalletSectionHead"><strong>شارژ کیف پول</strong><span>درگاه و کارت‌به‌کارت</span></div>
            <div className="v2PaymentActions">
              <button onClick={() => run(async () => {
                const result = await authApi<{ redirect_url: string }>("/api/v1/wallet/topups/gateway", {
                  method: "POST",
                  body: JSON.stringify({ amount_toman: Number(walletTopup) }),
                });
                window.open(result.redirect_url, "_blank", "noopener,noreferrer");
              }, "لینک درگاه ساخته شد")}>زرین‌پال</button>
              <label>مبلغ<input type="number" value={walletTopup} onChange={(e) => setWalletTopup(e.target.value)} /></label>
              <label>رسید کارت‌به‌کارت<input type="file" accept="image/*,.pdf" onChange={(e) => setWalletReceipt(e.target.files?.[0] || null)} /></label>
              <button onClick={() => {
                if (!walletReceipt) return setError("رسید را انتخاب کنید");
                const fd = new FormData();
                fd.append("amount_toman", walletTopup);
                fd.append("receipt", walletReceipt);
                run(() => authApi("/api/v1/wallet/topups/card", { method: "POST", body: fd }), "رسید ارسال شد");
              }}>ارسال رسید کارت</button>
            </div>
          </section>
        )}

        <section className="primeWalletLedger">
          <div className="primeWalletSectionHead icon">
            <div className="primeWalletLedgerIcon"><CreditCard size={24} /></div>
            <div><strong>گردش کیف پول</strong><span>آخرین {transactions.length.toLocaleString("fa-IR")} تراکنش</span></div>
          </div>

          <div className="primeWalletTableHead">
            <span>نوع</span><span>مبلغ</span><span>زمان</span><span>توضیحات</span>
          </div>

          {transactions.length ? (
            <div className="primeWalletRows">
              {transactions.map((transaction) => (
                <div className="primeWalletRow" key={transaction.id}>
                  <span>{transaction.type}</span>
                  <strong className={Number(transaction.amount_toman) >= 0 ? "plus" : "minus"}>{money(transaction.amount_toman)}</strong>
                  <span>{dt(transaction.created_at)}</span>
                  <span>{transaction.description || "—"}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="primeWalletEmpty">
              <span><CreditCard size={43} /></span>
              <strong>تراکنشی یافت نشد</strong>
              <p>هنوز هیچ تراکنشی در کیف پول شما ثبت نشده است.</p>
            </div>
          )}
        </section>
      </div>
    );
  }

  function renderCommerce() {
    return (
      <div className="primeCommercePage">
        <div className="primeCommerceTabs">
          <button className={commerceTab === "payments" ? "active" : ""} onClick={() => setCommerceTab("payments")}><CreditCard size={19} />پرداخت‌ها</button>
          <button className={commerceTab === "orders" ? "active" : ""} onClick={() => setCommerceTab("orders")}><Boxes size={19} />سفارش‌ها</button>
          <button className={commerceTab === "customers" ? "active" : ""} onClick={() => setCommerceTab("customers")}><Users size={19} />مشتری‌ها</button>
        </div>

        {commerceTab === "payments" && (
          <section className="primeCommercePanel">
            <div className="primeCommerceSearch">
              <button onClick={() => loadPayments(1)}><Search size={24} /></button>
              <input
                value={paymentSearch}
                onChange={(e) => setPaymentSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && loadPayments(1)}
                placeholder="جستجو در پرداخت‌ها"
              />
              <i />
            </div>

            <div className="primeCommerceFilters">
              <label>
                <PrimeSelect
                  value={paymentStatus}
                  onChange={setPaymentStatus}
                  options={[
                    { value: "", label: "همه وضعیت‌ها" },
                    { value: "pending", label: "در انتظار" },
                    { value: "awaiting_review", label: "نیازمند بررسی" },
                    { value: "paid", label: "پرداخت‌شده" },
                    { value: "rejected", label: "ردشده" },
                    { value: "failed", label: "ناموفق" },
                  ]}
                />
                <ChevronLeft size={17} />
              </label>
              <label>
                <PrimeSelect
                  value={paymentMethod}
                  onChange={setPaymentMethod}
                  options={[
                    { value: "", label: "همه روش‌ها" },
                    { value: "gateway", label: "درگاه" },
                    { value: "card_to_card", label: "کارت‌به‌کارت" },
                    { value: "customer_wallet", label: "کیف پول مشتری" },
                  ]}
                />
                <ChevronLeft size={17} />
              </label>
              <label>
                <PrimeSelect
                  value={paymentDate}
                  onChange={setPaymentDate}
                  options={[
                    { value: "", label: "همه تاریخ‌ها" },
                    { value: "today", label: "امروز" },
                  ]}
                />
                <ChevronLeft size={17} />
              </label>
              <button onClick={() => loadPayments(1)}>اعمال</button>
            </div>

            <div className="primeCommerceTable">
              <div className="primeCommerceTableHead">
                <span>مبلغ</span><span>روش</span><span>کاربر</span><span>تاریخ</span><span>توضیحات</span>
              </div>
              <div className="primeCommerceTableBody">
                {paymentsPage.items.map((payment) => (
                  <div className="primeCommerceRow" key={payment.id}>
                    <strong>{money(payment.amount_toman)}</strong>
                    <span>{payment.method}</span>
                    <span>{payment.customer_name || payment.admin_username || "—"}</span>
                    <span>{dt(payment.created_at)}</span>
                    <div>
                      <span>{payment.purpose || payment.status}</span>
                      <div className="v2Inline">
                        {payment.method === "card_to_card" && <button onClick={() => viewReceipt(payment.id)}>رسید</button>}
                        {payment.status === "awaiting_review" && (user.role === "owner" || payment.purpose !== "admin_wallet_topup") && <>
                          <button className="ok" onClick={() => reviewPayment(payment, true)}><Check size={14} /></button>
                          <button className="danger" onClick={() => openConfirmAction({
                            title: "رد پرداخت",
                            description: `پرداخت ${money(payment.amount_toman)} رد شود؟`,
                            submitLabel: "رد پرداخت",
                            successMessage: "پرداخت رد شد",
                            action: () => authApi(`/api/v1/payments/${payment.id}/review`, {
                              method: "POST",
                              body: JSON.stringify({ approved: false, note: "Rejected from panel" }),
                            }),
                          })}><X size={14} /></button>
                        </>}
                      </div>
                    </div>
                  </div>
                ))}

                {!paymentsPage.items.length && (
                  <div className="primeCommerceEmpty">
                    <span><CreditCard size={47} /></span>
                    <strong>پرداختی ثبت نشده است</strong>
                    <p>هنوز هیچ پرداختی در سیستم ثبت نشده است.</p>
                  </div>
                )}
              </div>
              <div className="primeCommercePager">
                <span>{paymentsPage.total.toLocaleString("fa-IR")} ردیف</span>
                <div>
                  <button disabled={paymentsPage.page <= 1} onClick={() => loadPayments(paymentsPage.page - 1)}><ChevronRight size={21} /></button>
                  <b>{paymentsPage.page.toLocaleString("fa-IR")} / {Math.max(paymentsPage.pages, 1).toLocaleString("fa-IR")}</b>
                  <button disabled={paymentsPage.page >= paymentsPage.pages} onClick={() => loadPayments(paymentsPage.page + 1)}><ChevronLeft size={21} /></button>
                </div>
              </div>
            </div>
          </section>
        )}

        {commerceTab === "orders" && (
          <section className="primeCommercePanel">
            <div className="primeCommerceTable">
              <div className="primeCommerceTableHead"><span>سفارش</span><span>حجم</span><span>مبلغ</span><span>پرداخت</span><span>وضعیت</span></div>
              <div className="primeCommerceTableBody">
                {ordersPage.items.map((order) => (
                  <div className="primeCommerceRow" key={order.id}>
                    <div><strong>{order.id.slice(0, 8)}</strong><small>{dt(order.created_at)}</small></div>
                    <span>{gib(order.quota_bytes)}</span>
                    <strong>{money(order.retail_amount_toman)}</strong>
                    <span>{order.payment_method}</span>
                    <span>{order.status}</span>
                  </div>
                ))}
                {!ordersPage.items.length && <div className="primeCommerceEmpty"><span><Boxes size={47} /></span><strong>سفارشی ثبت نشده است</strong><p>هنوز سفارشی در سیستم ثبت نشده است.</p></div>}
              </div>
              <div className="primeCommercePager">
                <span>{ordersPage.total.toLocaleString("fa-IR")} ردیف</span>
                <div>
                  <button disabled={ordersPage.page <= 1} onClick={() => loadOrders(ordersPage.page - 1)}><ChevronRight size={21} /></button>
                  <b>{ordersPage.page.toLocaleString("fa-IR")} / {Math.max(ordersPage.pages, 1).toLocaleString("fa-IR")}</b>
                  <button disabled={ordersPage.page >= ordersPage.pages} onClick={() => loadOrders(ordersPage.page + 1)}><ChevronLeft size={21} /></button>
                </div>
              </div>
            </div>
          </section>
        )}

        {commerceTab === "customers" && (
          <section className="primeCommercePanel">
            <div className="primeCommerceSearch">
              <button onClick={() => loadCustomers(1)}><Search size={24} /></button>
              <input value={customerSearch} onChange={(e) => setCustomerSearch(e.target.value)} placeholder="جستجوی مشتری" />
              <i />
            </div>
            <div className="primeCommerceTable">
              <div className="primeCommerceTableHead"><span>مشتری</span><span>Telegram</span><span>کیف پول</span><span>تاریخ عضویت</span><span>وضعیت</span></div>
              <div className="primeCommerceTableBody">
                {customersPage.items.map((customer) => (
                  <div className="primeCommerceRow" key={customer.id}>
                    <div><strong>{customer.display_name || customer.username || "بدون نام"}</strong><small>@{customer.username || "—"}</small></div>
                    <span>{customer.telegram_user_id || "—"}</span>
                    <strong>{money(customer.wallet_balance_toman)}</strong>
                    <span>{dt(customer.created_at)}</span>
                    <span>فعال</span>
                  </div>
                ))}
                {!customersPage.items.length && <div className="primeCommerceEmpty"><span><Users size={47} /></span><strong>مشتری ثبت نشده است</strong><p>هنوز مشتری‌ای در سیستم ثبت نشده است.</p></div>}
              </div>
              <div className="primeCommercePager">
                <span>{customersPage.total.toLocaleString("fa-IR")} ردیف</span>
                <div>
                  <button disabled={customersPage.page <= 1} onClick={() => loadCustomers(customersPage.page - 1)}><ChevronRight size={21} /></button>
                  <b>{customersPage.page.toLocaleString("fa-IR")} / {Math.max(customersPage.pages, 1).toLocaleString("fa-IR")}</b>
                  <button disabled={customersPage.page >= customersPage.pages} onClick={() => loadCustomers(customersPage.page + 1)}><ChevronLeft size={21} /></button>
                </div>
              </div>
            </div>
          </section>
        )}
      </div>
    );
  }

  function renderBots() {
    return (
      <div className="primeBotsPage">
        <section className="primeBotsPanel">
          <div className="primeBotsPanelHead">
            <div className="primeBotsTitleIcon"><Database size={26} /></div>
            <div><strong>ربات‌های فروش</strong><span>مدیریت ربات‌های فروش پیامکی، کارتی و درگاه پرداخت</span></div>
            <div className="primeBotsHeroIcon"><Bot size={34} /></div>
          </div>

          <div className="primeBotsTable">
            <div className="primeBotsTableHead">
              <span>نام</span><span>کیف پول</span><span>کارت</span><span>درگاه</span><span>وضعیت</span>
            </div>
            <div className="primeBotsTableBody">
              {bots.map((bot) => (
                <button className="primeBotRow" key={bot.id} onClick={() => openBotManage(bot)}>
                  <div><strong>{bot.name}</strong><small>@{bot.username || "—"}</small></div>
                  <span>{bot.customer_wallet_enabled ? "فعال" : "خاموش"}</span>
                  <span>{bot.card_to_card_enabled ? "فعال" : "خاموش"}</span>
                  <span>{bot.gateway_enabled ? "فعال" : "خاموش"}</span>
                  <span className={bot.enabled ? "primeBotStatus active" : "primeBotStatus disabled"}>{bot.enabled ? "فعال" : "خاموش"}</span>
                </button>
              ))}
              {!bots.length && (
                <div className="primeBotsEmpty">
                  <span><Bot size={55} /></span>
                  <strong>رباتی ثبت نشده</strong>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    );
  }

  function renderPasarguard() {
    return (
      <div className="primePasarguardPage">
        <section className="primePasarguardPanel">
          <div className="primePasarguardPanelHead">
            <div className="primePasarguardTitleIcon"><Database size={26} /></div>
            <div><strong>اتصال‌های PasarGuard</strong><span>مدیریت و نظارت بر اتصال‌های PasarGuard</span></div>
          </div>

          <div className="primePasarguardTable">
            <div className="primePasarguardTableHead">
              <span>نام</span><span>آدرس</span><span>آخرین Sync</span><span>وضعیت</span>
            </div>
            <div className="primePasarguardTableBody">
              {connections.map((connection) => (
                <button
                  className="primePasarguardRow"
                  key={connection.id}
                  onClick={() => { setSelectedId(connection.id); setModal("connection-manage"); }}
                >
                  <div><strong>{connection.name}</strong>{connection.last_error && <small>{connection.last_error}</small>}</div>
                  <span>{connection.base_url}</span>
                  <span>{dt(connection.last_sync_at)}</span>
                  <span className={connection.enabled ? "primePasarguardStatus active" : "primePasarguardStatus disabled"}>{connection.enabled ? "فعال" : "خاموش"}</span>
                </button>
              ))}

              {!connections.length && (
                <div className="primePasarguardEmpty">
                  <span><ShieldCheck size={57} /></span>
                  <strong>اتصالی ثبت نشده</strong>
                  <p>برای افزودن اتصال جدید روی دکمه + افزودن کلیک کنید.</p>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    );
  }

  function renderReports() {
    return (
      <div className="primeReportsPage">
        <section className="primeReportMetrics">
          <article className="primeReportMetric cyan">
            <div className="primeReportMetricIcon"><Wallet size={26} /></div>
            <div><span>درآمد کل</span><strong>{money(financial?.sales_toman)}</strong><small>درآمد از فروش و تمدید</small></div>
            <i><Activity size={19} /></i>
          </article>
          <article className="primeReportMetric violet">
            <div className="primeReportMetricIcon"><Activity size={26} /></div>
            <div><span>حجم مصرف</span><strong>{gib(summary?.lifetime_usage_bytes || 0)}</strong><small>کل ترافیک مصرف‌شده</small></div>
            <i><Activity size={19} /></i>
          </article>
          <article className="primeReportMetric emerald">
            <div className="primeReportMetricIcon"><Users size={26} /></div>
            <div><span>تعداد کاربران</span><strong>{(summary?.clients || 0).toLocaleString("fa-IR")}</strong><small>کاربران فعال سیستم</small></div>
            <i><Activity size={19} /></i>
          </article>
          <article className="primeReportMetric orange">
            <div className="primeReportMetricIcon"><Database size={26} /></div>
            <div><span>سفارش‌های فعال‌سازی</span><strong>{(financial?.provisioned_orders || 0).toLocaleString("fa-IR")}</strong><small>سفارش‌های تهیه‌شده</small></div>
            <i><Activity size={19} /></i>
          </article>
        </section>

        {user.role === "owner" && (
          <section className="primeAuditPanel">
            <div className="primeAuditHead">
              <div className="primeAuditIcon"><ShieldCheck size={27} /></div>
              <div><strong>Audit Log</strong><span>سوابق حساب‌های سیستم</span></div>
              <div className="primeAuditSideIcon"><CreditCard size={27} /></div>
            </div>

            <div className="primeAuditTable">
              <div className="primeAuditTableHead">
                <span>حساب</span><span>Entity</span><span>IP</span><span>عملیات</span><span>زمان</span>
              </div>
              <div className="primeAuditTableBody">
                {audits.map((audit) => (
                  <div className="primeAuditRow" key={audit.id}>
                    <span>{audit.entity_type}</span>
                    <span>{audit.entity_id || "—"}</span>
                    <span>{audit.ip_address || "—"}</span>
                    <strong>{audit.action}</strong>
                    <span>{dt(audit.created_at)}</span>
                  </div>
                ))}

                {!audits.length && (
                  <div className="primeAuditEmpty">
                    <span><Search size={48} /></span>
                    <strong>رویدادی ثبت نشده</strong>
                    <p>در حال حاضر هیچ رویدادی در سیستم وجود ندارد.</p>
                  </div>
                )}
              </div>
            </div>
          </section>
        )}
      </div>
    );
  }

  function renderSettings() {
    return (
      <div className="primeSettingsPage">
        <section className="primeSettingsCard primeBankSection">
          <div className="primeSettingsHead">
            <div className="primeSettingsIcon"><CreditCard size={25} /></div>
            <div><strong>کارت‌های بانکی</strong><span>مدیریت کارت‌های پرداخت و تسویه</span></div>
            <button className="primeSettingsAdd" onClick={() => setModal("bank-card")}><Plus size={20} /> کارت</button>
          </div>
          <div className="primeBankBody">
            {bankCards.length ? (
              <div className="primeBankGrid">
                {bankCards.map((card) => (
                  <div className="primeBankItem" key={card.id}>
                    <div><strong>{card.title}</strong>{card.is_default && <span>پیش‌فرض</span>}</div>
                    <b>{card.card_number.replace(/(\d{4})(?=\d)/g, "$1 ")}</b>
                    <small>{card.card_holder_name || "—"}</small>
                    <div>
                      {!card.is_default && <button onClick={() => run(() => authApi(`/api/v1/bank-cards/${card.id}`, { method: "PATCH", body: JSON.stringify({ is_default: true }) }), "کارت پیش‌فرض شد")}>پیش‌فرض</button>}
                      <button className="danger" onClick={() => openConfirmAction({
                        title: "حذف کارت بانکی",
                        description: `کارت ${card.title} حذف شود؟`,
                        submitLabel: "حذف کارت",
                        successMessage: "کارت حذف شد",
                        action: () => authApi(`/api/v1/bank-cards/${card.id}`, { method: "DELETE" }),
                      })}>حذف</button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="primeSettingsEmpty">
                <span><CreditCard size={46} /></span>
                <strong>هنوز کارت بانکی اضافه نشده است.</strong>
                <p>برای افزودن کارت بانکی روی دکمه «+ کارت» کلیک کنید.</p>
              </div>
            )}
          </div>
        </section>

        <section className="primeSettingsCard primeGatewaySection">
          <div className="primeSettingsHead">
            <div className="primeSettingsIcon"><WalletCards size={25} /></div>
            <div><strong>زرین‌پال</strong><span>درگاه پرداخت متصل به پنل</span></div>
            <strong className="primeZarinpalMark">Z.</strong>
          </div>
          <div className="primeGatewayBody">
            <label>
              <span>شناسه پذیرنده (Merchant ID)</span>
              <input
                type="password"
                placeholder={paymentProfile?.gateway_configured ? "برای تغییر Merchant ID وارد کنید" : "Merchant ID"}
                value={gatewayMerchant}
                onChange={(e) => setGatewayMerchant(e.target.value)}
              />
            </label>
            <label className="primeGatewayCheck">
              <input
                type="checkbox"
                checked={Boolean(paymentProfile?.gateway_enabled)}
                onChange={(e) => setPaymentProfile((old) => old ? { ...old, gateway_enabled: e.target.checked } : old)}
              />
              <span>درگاه فعال</span>
            </label>
            <button className="primeSettingsPrimary" onClick={() => run(() => authApi("/api/v1/payment-profile", {
              method: "PUT",
              body: JSON.stringify({
                gateway_provider: "zarinpal",
                gateway_enabled: Boolean(paymentProfile?.gateway_enabled),
                gateway_credentials: gatewayMerchant ? { merchant_id: gatewayMerchant } : null,
                card_to_card_enabled: true,
                card_number: null,
                card_holder_name: null,
                card_instructions: null,
              }),
            }), "تنظیمات زرین‌پال ذخیره شد")}>ذخیره زرین‌پال</button>
          </div>
        </section>

        <section className="primeSettingsCard primeThemeSection">
          <div className="primeSettingsHead">
            <div className="primeSettingsIcon"><Settings size={25} /></div>
            <div><strong>ظاهر پنل</strong><span>انتخاب تم رنگی پنل مدیریت</span></div>
          </div>
          <div className="primeThemeOptions">
            <button className={theme === "dark" ? "active" : ""} onClick={() => setTheme("dark")}><i className="dark" />Dark</button>
            <button className={theme === "light" ? "active" : ""} onClick={() => setTheme("light")}><i className="light" />Light</button>
            <button className={accent === "cyan" ? "active" : ""} onClick={() => setAccent("cyan")}><i className="cyan" />cyan</button>
            <button className={accent === "violet" ? "active" : ""} onClick={() => setAccent("violet")}><i className="violet" />violet</button>
            <button className={accent === "emerald" ? "active" : ""} onClick={() => setAccent("emerald")}><i className="emerald" />emerald</button>
            <button className={accent === "orange" ? "active" : ""} onClick={() => setAccent("orange")}><i className="orange" />orange</button>
          </div>
        </section>

        {user.role === "owner" && (
          <section className="primeSettingsCard primeSecuritySection">
            <div className="primeSettingsHead">
              <div className="primeSettingsIcon"><ShieldCheck size={25} /></div>
              <div><strong>امنیت Owner</strong><span>مدیریت امنیت حساب و احراز هویت دو مرحله‌ای</span></div>
            </div>
            <div className="primeSecurityBody">
              <div>
                <p><ShieldCheck size={18} /><span>Recovery Codes: 2FA</span><small>پشتیبان‌گیری کدهای بازیابی</small></p>
                <p><ShieldCheck size={18} /><span>وضعیت: {twoFactor?.enabled ? "فعال" : "غیرفعال"}</span><small>احراز هویت دو مرحله‌ای پنل</small></p>
              </div>
              {!twoFactor?.enabled ? (
                <button className="primeSecurityButton" disabled={busy} onClick={openEnable2FA}>فعال‌سازی 2FA</button>
              ) : (
                <button className="primeSecurityButton" disabled={busy} onClick={openDisable2FA}>غیرفعال‌کردن 2FA</button>
              )}
            </div>
          </section>
        )}

        {user.role === "owner" && (
          <section className="primeSettingsCard primeBackupSection">
            <div className="primeSettingsHead">
              <div className="primeSettingsIcon"><Database size={25} /></div>
              <div><strong>Backup & Recovery</strong><span>پشتیبان‌گیری و بازیابی اطلاعات پنل</span></div>
            </div>
            <div className="primeBackupRows">
              <button onClick={exportBackup}><span><CreditCard size={21} /></span><div><strong>دانلود فایل پشتیبان</strong><small>تهیه نسخه پشتیبان از تمام اطلاعات</small></div><ChevronLeft size={19} /></button>
              <label><span><CreditCard size={21} /></span><div><strong>بازیابی اطلاعات</strong><small>{backupFile?.name || "انتخاب فایل پشتیبان برای بازیابی"}</small></div><input type="file" accept=".pvbackup" onChange={(e) => setBackupFile(e.target.files?.[0] || null)} /><ChevronLeft size={19} /></label>
              <button onClick={restoreBackup}><span><Settings size={21} /></span><div><strong>Merge Restore</strong><small>ادغام نسخه پشتیبان با اطلاعات فعلی</small></div><ChevronLeft size={19} /></button>
            </div>
          </section>
        )}
      </div>
    );
  }

  function pageContent() {
    if (section === "dashboard") return renderDashboard();
    if (section === "admins") return renderAdmins();
    if (section === "clients") return renderClients();
    if (section === "plans") return renderPlans();
    if (section === "wallet") return renderWallet();
    if (section === "commerce") return renderCommerce();
    if (section === "bots") return renderBots();
    if (section === "pasarguard") return renderPasarguard();
    if (section === "reports") return renderReports();
    return renderSettings();
  }

  return (
    <main className="v2App">
      <header className={["dashboard", "admins", "clients", "plans", "wallet", "commerce", "bots", "pasarguard", "reports", "settings"].includes(section) ? "v2Topbar primeDashTopbar" : "v2Topbar"}>
        <div className={["dashboard", "admins", "clients", "plans", "wallet", "commerce", "bots", "pasarguard", "reports", "settings"].includes(section) ? "v2Brand primeDashBrand" : "v2Brand"}>
          <div className="v2BrandMark">{["dashboard", "admins", "clients", "plans", "wallet", "commerce", "bots", "pasarguard", "reports", "settings"].includes(section) ? <ShieldCheck size={22} /> : <Gauge size={21} />}</div>
          <div><strong>PRIMEVPN</strong><span>{user.role === "owner" ? "OWNER CONTROL" : "RESELLER PANEL"}</span></div>
        </div>
        <div className={["dashboard", "admins", "clients", "plans", "wallet", "commerce", "bots", "pasarguard", "reports", "settings"].includes(section) ? "v2TopActions primeDashTopActions" : "v2TopActions"}>
          <button className="v2MenuButton" title="منو" onClick={() => setDrawer(true)}><MoreVertical size={23} /></button>
          <button title="بروزرسانی" onClick={reloadSection}><RefreshCw size={18} /></button>
          {section === "dashboard" && (
            <button
              title="اعلان‌ها"
              className="primeDashBell"
              onClick={() => document.getElementById("prime-dashboard-notifications")?.scrollIntoView({ behavior: "smooth", block: "center" })}
            >
              <Bell size={19} />
              {unread > 0 && <i>{unread}</i>}
            </button>
          )}
        </div>
      </header>

      {drawer && (
        <div className="v2DrawerBackdrop primeDrawerBackdrop" onMouseDown={() => setDrawer(false)}>
          <aside className="v2Drawer primeDrawer" onMouseDown={(e) => e.stopPropagation()}>
            <div className="v2DrawerHead primeDrawerHead">
              <button className="primeDrawerClose" onClick={() => setDrawer(false)} aria-label="بستن منو">
                <X size={31} />
              </button>
              <div className="primeDrawerIdentity">
                <strong>PRIMEVPN {user.role === "owner" ? "Owner" : "Admin"}</strong>
                <span>{user.role}</span>
              </div>
            </div>
            <nav className="primeDrawerNav">
              {visibleNav.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.key}
                    className={section === item.key ? "active" : ""}
                    onClick={() => go(item.key)}
                  >
                    <span className="primeDrawerIcon"><Icon size={25} /></span>
                    <span className="primeDrawerLabel">{item.label}</span>
                    {item.key === "dashboard" && unread > 0 && <i>{unread}</i>}
                  </button>
                );
              })}
            </nav>
            <button className="v2Logout primeDrawerLogout" onClick={signOut}>
              <LogOut size={26} />
              <span>خروج</span>
            </button>
          </aside>
        </div>
      )}

      <section className="v2Content">
        <div className={section === "dashboard" ? "v2PageHead primeDashPageHead" : section === "admins" ? "v2PageHead primeAdminPageHead" : section === "clients" ? "v2PageHead primeClientPageHead" : section === "plans" ? "v2PageHead primePlanPageHead" : section === "wallet" ? "v2PageHead primeWalletPageHead" : section === "commerce" ? "v2PageHead primeCommercePageHead" : section === "bots" ? "v2PageHead primeBotsPageHead" : section === "pasarguard" ? "v2PageHead primePasarguardPageHead" : section === "reports" ? "v2PageHead primeReportsPageHead" : section === "settings" ? "v2PageHead primeSettingsPageHead" : "v2PageHead"}>
          <div>
            <span className="v2Eyebrow">PRIME NETWORK · PRODUCTION</span>
            <h1>{activeNav.label}</h1>
            <p>{section === "dashboard" ? (user.role === "owner" ? "مرکز مدیریت مرکزی" : "مرکز مدیریت نماینده") : (user.role === "owner" ? "مرکز مدیریت مرکزی" : "پنل مستقل نماینده")}</p>
          </div>
          {canCreate && (
            <button className="v2Create" onClick={contextualCreate}><Plus size={19} /><span>افزودن</span></button>
          )}
        </div>

        {error && <div className="v2Alert error">{error}<button onClick={() => setError("")}><X size={15} /></button></div>}
        {success && <div className="v2Alert success">{success}<button onClick={() => setSuccess("")}><X size={15} /></button></div>}

        {pageContent()}
      </section>

      {canCreate && !["admins", "clients", "plans", "bots", "pasarguard"].includes(section) && <button className="v2Fab" onClick={contextualCreate}><Plus size={25} /></button>}

      <Modal open={modal === "admin-create"} title="ساخت نماینده" onClose={() => setModal(null)}>
        <form className="v2Form primeCreateForm primeAdminCreateForm" onSubmit={createAdmin}>
          <label>نام کاربری<input value={adminForm.username} onChange={(e) => setAdminForm({ ...adminForm, username: e.target.value })} required /></label>
          <label>نام نمایشی<input value={adminForm.display_name} onChange={(e) => setAdminForm({ ...adminForm, display_name: e.target.value })} /></label>
          <label>شناسه تلگرام<input type="number" value={adminForm.telegram_id} onChange={(e) => setAdminForm({ ...adminForm, telegram_id: e.target.value })} /></label>
          <label>رمز عبور<input type="password" minLength={10} value={adminForm.password} onChange={(e) => setAdminForm({ ...adminForm, password: e.target.value })} required /></label>
          <label>موجودی اولیه<input type="number" value={adminForm.initial_balance_toman} onChange={(e) => setAdminForm({ ...adminForm, initial_balance_toman: e.target.value })} /></label>
          <button className="v2Primary" disabled={busy}>ساخت نماینده</button>
        </form>
      </Modal>

      <Modal open={modal === "admin-manage" && Boolean(selectedAdmin)} title={selectedAdmin ? `مدیریت ${selectedAdmin.username}` : "مدیریت نماینده"} onClose={() => setModal(null)} wide>
        {selectedAdmin && <div className="v2Stack">
          <section className="v2Metrics compact">
            <article className="v2Metric"><span>کیف پول</span><strong>{money(selectedAdmin.wallet_balance_toman)}</strong><small>{selectedAdmin.client_count.toLocaleString("fa-IR")} کلاینت</small></article>
            <article className="v2Metric"><span>وضعیت حساب</span><strong>{statusFa(selectedAdmin.status)}</strong><small>{selectedAdmin.telegram_id ? `شناسه تلگرام: ${selectedAdmin.telegram_id}` : "شناسه تلگرام ثبت نشده"}</small></article>
          </section>
          <article className="v2Card nested primeAutoPlansCard">
            <div className="v2CardHead">
              <div>
                <strong>پلن‌های فعال نماینده</strong>
                <span>تمام پلن‌های فعال مالک به‌صورت خودکار برای همه نمایندگان در دسترس هستند.</span>
              </div>
            </div>
            <div className="v2Catalog">
              {adminAssignments.map((p) => <div className="v2CatalogRow" key={p.plan_id}>
                <div>
                  <strong>{p.name}</strong>
                  <span>قیمت فروش: {money(p.retail_price_per_gib_toman)} / GB</span>
                </div>
                <span className="primeAutoBadge">{p.automatic ? "خودکار" : "قیمت سفارشی"}</span>
              </div>)}
              {!adminAssignments.length && <Empty text="پلن فعالی در پنل تعریف نشده است." />}
            </div>
          </article>
          <div className="v2ActionGrid">
            <button onClick={() => openAdminWalletTopup(selectedAdmin)}>شارژ کیف پول</button>
            <button onClick={() => openAdminEdit(selectedAdmin)}>ویرایش مشخصات</button>
            <button className="danger" onClick={() => selectedAdmin.status === "active"
              ? openConfirmAction({
                  title: "غیرفعال‌کردن نماینده",
                  description: `نماینده ${selectedAdmin.display_name || selectedAdmin.username} غیرفعال شود؟`,
                  submitLabel: "غیرفعال‌کردن",
                  successMessage: "نماینده غیرفعال شد",
                  action: () => authApi(`/api/v1/admins/${selectedAdmin.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({ status: "disabled" }),
                  }),
                })
              : run(() => authApi(`/api/v1/admins/${selectedAdmin.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({ status: "active" }),
                }), "نماینده فعال شد")
            }>{selectedAdmin.status === "active" ? "غیرفعال‌کردن" : "فعال‌کردن"}</button>
          </div>
        </div>}
      </Modal>

      <Modal open={modal === "client-create"} title="ساخت کلاینت" onClose={() => setModal(null)}>
        <form className="v2Form primeCreateForm primeClientCreateForm" onSubmit={createClient}>
          <label>نام کاربری<input value={clientForm.username} onChange={(e) => setClientForm({ ...clientForm, username: e.target.value })} required /></label>
          {user.role === "owner" && <div className="v2Picker">
            <label>جستجوی نماینده
              <div className="v2PickerSearch"><input value={adminPickerSearch} onChange={(e) => setAdminPickerSearch(e.target.value)} placeholder="نام کاربری یا نام نماینده" /><button type="button" onClick={() => searchAdminOptions()}>جستجو</button></div>
            </label>
            <label>نماینده
              <PrimeSelect
                value={clientForm.admin_id}
                onChange={chooseClientAdmin}
                placeholder="انتخاب نماینده"
                options={adminOptions.map((a) => ({ value: a.id, label: `${a.display_name || a.username} (@${a.username})` }))}
              />
            </label>
          </div>}
          <label>پلن
            <PrimeSelect
              value={clientForm.plan_id}
              onChange={(value) => setClientForm({ ...clientForm, plan_id: value })}
              placeholder={user.role === "owner" && !clientForm.admin_id ? "ابتدا نماینده را انتخاب کنید" : "انتخاب پلن"}
              disabled={user.role === "owner" && !clientForm.admin_id}
              options={(user.role === "owner" ? clientPlanOptions : plans)
                .filter((p) => p.enabled !== false)
                .map((p) => ({ value: p.id, label: p.name }))}
            />
            {user.role === "owner" && clientForm.admin_id && !clientPlanOptions.length && (
              <small className="primeFieldHint warn">برای این نماینده هنوز پلنی تخصیص داده نشده است.</small>
            )}
          </label>
          <label>حجم GB<input type="number" step="0.1" value={clientForm.quota_gib} onChange={(e) => setClientForm({ ...clientForm, quota_gib: e.target.value })} required /></label>
          <label>مدت روز<input type="number" value={clientForm.duration_days} onChange={(e) => setClientForm({ ...clientForm, duration_days: e.target.value })} /></label>
          <label>تعداد دستگاه<input type="number" value={clientForm.hwid_limit} onChange={(e) => setClientForm({ ...clientForm, hwid_limit: e.target.value })} /></label>
          <button className="v2Primary" disabled={busy}>ساخت کلاینت</button>
        </form>
      </Modal>

      <Modal open={modal === "client-manage" && Boolean(selectedClient)} title={selectedClient ? selectedClient.username : "کلاینت"} onClose={() => setModal(null)} wide>
        {selectedClient && <div className="v2Stack">
          <section className="v2Metrics compact">
            <article className="v2Metric"><span>مصرف کل</span><strong>{gib(selectedClient.lifetime_usage_bytes)}</strong><small>مصرف مادام‌العمر</small></article>
            <article className="v2Metric"><span>حجم</span><strong>{selectedClient.quota_bytes ? gib(selectedClient.quota_bytes) : "∞"}</strong><small>{selectedClient.hwid_limit || "∞"} دستگاه</small></article>
            <article className="v2Metric"><span>انقضا</span><strong>{dt(selectedClient.expires_at)}</strong><small>{statusFa(selectedClient.status)}</small></article>
          </section>
          {selectedClient.subscription_url && <div className="v2QrInline">
            <QRCodeSVG value={selectedClient.subscription_url} size={150} />
            <div><strong>لینک اشتراک</strong><span>{selectedClient.subscription_url}</span><button onClick={() => navigator.clipboard.writeText(selectedClient.subscription_url || "")}><Copy size={14} /> کپی</button></div>
          </div>}
          <div className="v2ActionGrid">
            <button onClick={() => openClientEdit(selectedClient)}>ویرایش حجم، مدت و دستگاه</button>
            <button onClick={() => run(() => authApi(`/api/v1/clients/${selectedClient.id}/reset-usage`, { method: "POST" }), "مصرف بازنشانی شد")}>بازنشانی مصرف</button>
            <button onClick={() => run(() => authApi(`/api/v1/clients/${selectedClient.id}/revoke-subscription`, { method: "POST" }), "لینک اشتراک تغییر کرد")}>تغییر لینک اشتراک</button>
            <button className="danger" onClick={() => selectedClient.status === "active"
              ? openConfirmAction({
                  title: "غیرفعال‌کردن کلاینت",
                  description: `کلاینت ${selectedClient.username} غیرفعال شود؟`,
                  submitLabel: "غیرفعال‌کردن",
                  successMessage: "کلاینت غیرفعال شد",
                  action: () => authApi(`/api/v1/clients/${selectedClient.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({ disabled: true }),
                  }),
                })
              : run(() => authApi(`/api/v1/clients/${selectedClient.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({ disabled: false }),
                }), "کلاینت فعال شد")
            }>{selectedClient.status === "active" ? "غیرفعال‌کردن" : "فعال‌کردن"}</button>
          </div>
        </div>}
      </Modal>

      <Modal open={modal === "plan-create"} title="ساخت پلن پایه" onClose={() => setModal(null)}>
        <form className="v2Form primePlanCreateForm" onSubmit={createPlan}>
          <label>نام پلن<input value={planForm.name} onChange={(e) => setPlanForm({ ...planForm, name: e.target.value })} required /></label>
          <label>Group
            <PrimeSelect
              value={planForm.group_id}
              onChange={(value) => setPlanForm({ ...planForm, group_id: value })}
              placeholder="انتخاب Group"
              options={groups.map((g) => ({ value: g.id, label: g.name }))}
            />
          </label>
          <label>قیمت پایه هر GB<input type="number" value={planForm.base_price_per_gib_toman} onChange={(e) => setPlanForm({ ...planForm, base_price_per_gib_toman: e.target.value })} required /></label>
          <label>حداقل GB<input type="number" value={planForm.min_quota_gib} onChange={(e) => setPlanForm({ ...planForm, min_quota_gib: e.target.value })} /></label>
          <label>حداکثر GB<input type="number" value={planForm.max_quota_gib} onChange={(e) => setPlanForm({ ...planForm, max_quota_gib: e.target.value })} /></label>
          <label>حداکثر روز<input type="number" value={planForm.max_duration_days} onChange={(e) => setPlanForm({ ...planForm, max_duration_days: e.target.value })} /></label>
          <label>HWID پیش‌فرض<input type="number" value={planForm.default_hwid_limit} onChange={(e) => setPlanForm({ ...planForm, default_hwid_limit: e.target.value })} /></label>
          <button className="v2Primary">ساخت پلن</button>
        </form>
      </Modal>

      <Modal open={modal === "plan-manage" && Boolean(selectedPlan)} title={selectedPlan?.name || "پلن"} onClose={() => setModal(null)}>
        {selectedPlan && <div className="v2Stack">
          <div className="v2Info primePlanAutoInfo">
            <p>قیمت پایه: <b>{money(selectedPlan.base_price_per_gib_toman || selectedPlan.cost_per_gib_toman)} / GB</b></p>
            {user.role === "admin" && <p>قیمت فروش شما: <b>{money(selectedPlan.retail_price_per_gib_toman || selectedPlan.base_price_per_gib_toman)} / GB</b></p>}
            <p className="primeAutoPlanText">این پلن به‌صورت خودکار برای تمام نمایندگان فعال و تمام ربات‌های فروش آن‌ها در دسترس است.</p>
          </div>
          {user.role === "owner" ? <>
            <button onClick={() => openOwnerPlanEdit(selectedPlan)}>ویرایش پلن</button>
            <button className="v2Danger" onClick={() => openConfirmAction({
              title: "خاموش‌کردن پلن",
              description: `پلن «${selectedPlan.name}» برای همه نمایندگان و ربات‌ها خاموش شود؟`,
              submitLabel: "خاموش‌کردن پلن",
              successMessage: "پلن خاموش شد",
              action: () => authApi(`/api/v1/plans/${selectedPlan.id}`, { method: "DELETE" }),
            })}>خاموش‌کردن پلن</button>
          </> : <button onClick={() => openRetailPlanEdit(selectedPlan)}>تغییر قیمت فروش</button>}
        </div>}
      </Modal>

      <Modal open={modal === "connection-create"} title="افزودن PasarGuard" onClose={() => setModal(null)}>
        <form className="v2Form primeConnectionCreateForm" onSubmit={createConnection}>
          <label>نام اتصال<input value={connectionForm.name} onChange={(e) => setConnectionForm({ ...connectionForm, name: e.target.value })} required /></label>
          <label>آدرس پنل<input placeholder="https://panel.example.com" value={connectionForm.base_url} onChange={(e) => setConnectionForm({ ...connectionForm, base_url: e.target.value })} required /></label>
          <label>توکن API<input type="password" value={connectionForm.api_token} onChange={(e) => setConnectionForm({ ...connectionForm, api_token: e.target.value })} required /></label>
          <button className="v2Primary">تست و اضافه‌کردن</button>
        </form>
      </Modal>

      <Modal open={modal === "connection-manage" && Boolean(selectedConnection)} title={selectedConnection?.name || "PasarGuard"} onClose={() => setModal(null)}>
        {selectedConnection && <div className="v2ActionGrid">
          <button onClick={() => run(() => authApi(`/api/v1/connections/${selectedConnection.id}/test`, { method: "POST" }), "اتصال سالم است")}>تست اتصال</button>
          <button onClick={() => run(() => authApi(`/api/v1/connections/${selectedConnection.id}/sync-groups`, { method: "POST" }), "Groupها Sync شدند")}>همگام‌سازی گروه‌ها</button>
          <button onClick={() => openConnectionEdit(selectedConnection)}>ویرایش اتصال</button>
          <button className="v2Danger" onClick={() => openConfirmAction({
            title: "غیرفعال‌کردن اتصال",
            description: `اتصال PasarGuard «${selectedConnection.name}» غیرفعال شود؟`,
            submitLabel: "غیرفعال‌کردن",
            successMessage: "اتصال غیرفعال شد",
            action: () => authApi(`/api/v1/connections/${selectedConnection.id}`, { method: "DELETE" }),
          })}>غیرفعال‌کردن</button>
        </div>}
      </Modal>

      <Modal open={modal === "bot-create"} title="ساخت ربات فروش" onClose={() => setModal(null)}>
        <form className="v2Form primeBotCreateForm" onSubmit={createBot}>
          <label>نام ربات<input value={botForm.name} onChange={(e) => setBotForm({ ...botForm, name: e.target.value })} required /></label>
          <label>توکن ربات<input type="password" value={botForm.token} onChange={(e) => setBotForm({ ...botForm, token: e.target.value })} required /></label>
          {user.role === "owner" && <div className="v2Picker">
            <label>جستجوی نماینده
              <div className="v2PickerSearch"><input value={adminPickerSearch} onChange={(e) => setAdminPickerSearch(e.target.value)} placeholder="نام کاربری نماینده" /><button type="button" onClick={() => searchAdminOptions()}>جستجو</button></div>
            </label>
            <label>نماینده
              <PrimeSelect
                value={botForm.admin_id}
                onChange={(value) => setBotForm({ ...botForm, admin_id: value })}
                placeholder="انتخاب نماینده"
                options={adminOptions.map((a) => ({ value: a.id, label: `${a.display_name || a.username} (@${a.username})` }))}
              />
            </label>
          </div>}
          <label className="v2Check"><input type="checkbox" checked={botForm.customer_wallet_enabled} onChange={(e) => setBotForm({ ...botForm, customer_wallet_enabled: e.target.checked })} /> کیف پول مشتری</label>
          <label className="v2Check"><input type="checkbox" checked={botForm.card_to_card_enabled} onChange={(e) => setBotForm({ ...botForm, card_to_card_enabled: e.target.checked })} /> کارت‌به‌کارت</label>
          <label className="v2Check"><input type="checkbox" checked={botForm.gateway_enabled} onChange={(e) => setBotForm({ ...botForm, gateway_enabled: e.target.checked })} /> زرین‌پال</label>
          <button className="v2Primary">ثبت ربات</button>
        </form>
      </Modal>

      <Modal open={modal === "bot-manage" && Boolean(selectedBot)} title={selectedBot ? `مدیریت ${selectedBot.name}` : "مدیریت ربات"} onClose={() => setModal(null)} wide>
        {selectedBot && <div className="v2Stack">
          <section className="v2Metrics compact">
            <article className="v2Metric"><span>نام کاربری ربات</span><strong>@{selectedBot.username || "—"}</strong><small>{selectedBot.enabled ? "فعال" : "خاموش"}</small></article>
            <article className="v2Metric"><span>روش‌های پرداخت</span><strong>{[
              selectedBot.customer_wallet_enabled && "کیف پول",
              selectedBot.card_to_card_enabled && "کارت‌به‌کارت",
              selectedBot.gateway_enabled && "درگاه",
            ].filter(Boolean).join(" + ") || "هیچ"}</strong><small>از همین بخش قابل مدیریت است</small></article>
          </section>
          <article className="v2Card nested primeBotSyncCard">
            <div className="v2CardHead">
              <div>
                <strong>پلن‌های فروش ربات</strong>
                <span>پلن‌های فعال مالک به‌صورت خودکار در ربات نمایش داده می‌شوند و نماینده فقط قیمت فروش را تعیین می‌کند.</span>
              </div>
            </div>
            <div className="primeBotSyncState">
              <ShieldCheck size={25} />
              <div><strong>همگام‌سازی خودکار فعال است</strong><span>نیازی به انتخاب یا حذف دستی پلن برای این ربات نیست.</span></div>
            </div>
          </article>
          <div className="v2ActionGrid">
            <button onClick={() => run(() => authApi(`/api/v1/bots/${selectedBot.id}`, { method: "PATCH", body: JSON.stringify({ customer_wallet_enabled: !selectedBot.customer_wallet_enabled }) }), "وضعیت کیف پول تغییر کرد")}>کیف پول: {selectedBot.customer_wallet_enabled ? "فعال" : "خاموش"}</button>
            <button onClick={() => run(() => authApi(`/api/v1/bots/${selectedBot.id}`, { method: "PATCH", body: JSON.stringify({ card_to_card_enabled: !selectedBot.card_to_card_enabled }) }), "وضعیت کارت‌به‌کارت تغییر کرد")}>کارت‌به‌کارت: {selectedBot.card_to_card_enabled ? "فعال" : "خاموش"}</button>
            <button onClick={() => run(() => authApi(`/api/v1/bots/${selectedBot.id}`, { method: "PATCH", body: JSON.stringify({ gateway_enabled: !selectedBot.gateway_enabled }) }), "وضعیت درگاه تغییر کرد")}>درگاه: {selectedBot.gateway_enabled ? "فعال" : "خاموش"}</button>
            <button onClick={() => openBotEdit(selectedBot)}>نام و توکن</button>
            <button className="v2Danger" onClick={() => openConfirmAction({
              title: "خاموش‌کردن ربات",
              description: `ربات «${selectedBot.name}» خاموش شود؟ اتصال Webhook آن نیز غیرفعال می‌شود.`,
              submitLabel: "خاموش‌کردن ربات",
              successMessage: "ربات خاموش شد",
              action: () => authApi(`/api/v1/bots/${selectedBot.id}`, { method: "DELETE" }),
            })}>خاموش‌کردن</button>
          </div>
        </div>}
      </Modal>

      <Modal open={modal === "bank-card"} title="افزودن کارت بانکی" onClose={() => setModal(null)}>
        <form className="v2Form primeBankCardCreateForm" onSubmit={createCard}>
          <label>عنوان کارت<input value={cardForm.title} onChange={(e) => setCardForm({ ...cardForm, title: e.target.value })} /></label>
          <label>شماره کارت<input inputMode="numeric" placeholder="603799..." value={cardForm.card_number} onChange={(e) => setCardForm({ ...cardForm, card_number: e.target.value })} required /></label>
          <label>نام صاحب کارت<input value={cardForm.card_holder_name} onChange={(e) => setCardForm({ ...cardForm, card_holder_name: e.target.value })} /></label>
          <label>توضیحات<input value={cardForm.instructions} onChange={(e) => setCardForm({ ...cardForm, instructions: e.target.value })} /></label>
          <label className="v2Check"><input type="checkbox" checked={cardForm.is_default} onChange={(e) => setCardForm({ ...cardForm, is_default: e.target.checked })} /> کارت پیش‌فرض</label>
          <button className="v2Primary">ذخیره کارت</button>
        </form>
      </Modal>


      <Modal
        open={Boolean(actionDialog)}
        title={actionDialog?.title || "عملیات"}
        onClose={() => !busy && setActionDialog(null)}
      >
        {actionDialog && (
          <form className="v2Form primeActionDialog" onSubmit={submitActionDialog}>
            {actionDialog.description && <p className="primeActionDescription">{actionDialog.description}</p>}
            {actionDialog.notice && <pre className="primeActionNotice">{actionDialog.notice}</pre>}
            {actionDialog.fields.map((field) => (
              <label key={field.key}>
                {field.label}
                <input
                  type={field.type || "text"}
                  inputMode={field.type === "number" ? "numeric" : undefined}
                  value={actionValues[field.key] || ""}
                  placeholder={field.placeholder}
                  required={field.required}
                  autoComplete={field.type === "password" ? "new-password" : "off"}
                  onChange={(e) => setActionValues((old) => ({ ...old, [field.key]: e.target.value }))}
                />
              </label>
            ))}
            <button
              className={actionDialog.destructive ? "v2Primary primeActionDanger" : "v2Primary"}
              disabled={busy}
              type="submit"
            >
              {busy ? "در حال انجام..." : actionDialog.submitLabel}
            </button>
          </form>
        )}
      </Modal>
    </main>
  );
}
