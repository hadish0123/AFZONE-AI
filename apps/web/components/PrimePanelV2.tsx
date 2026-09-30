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
  customer_id?: string | null;
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
  assignment_id: string;
  plan_id: string;
  name: string;
  enabled: boolean;
  bot_visible: boolean;
  base_price_per_gib_toman: string;
  retail_price_per_gib_toman: string;
};

type BotCatalogRow = {
  plan_id: string;
  name: string;
  base_price_per_gib_toman: string;
  retail_price_per_gib_toman: string;
  enabled_in_bot: boolean;
  sort_order: number;
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
  const [adminPickerSearch, setAdminPickerSearch] = useState("");
  const [adminOptions, setAdminOptions] = useState<AdminRow[]>([]);
  const [assignmentPrice, setAssignmentPrice] = useState("");
  const [clientSearch, setClientSearch] = useState("");
  const [clientStatus, setClientStatus] = useState("");
  const [clientAdminFilter, setClientAdminFilter] = useState("");
  const [paymentStatus, setPaymentStatus] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("");
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
  const [botCatalog, setBotCatalog] = useState<BotCatalogRow[]>([]);
  const [botCatalogSelection, setBotCatalogSelection] = useState<string[]>([]);
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
        status_filter: paymentStatus,
        method: paymentMethod,
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
    if (section === "clients") await loadClients();
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
      if (user.role === "owner") await searchAdminOptions("");
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
    const data = await safe(() => authApi<BotCatalogRow[]>(`/api/v1/bots/${bot.id}/catalog`));
    if (data) {
      setBotCatalog(data);
      setBotCatalogSelection(data.filter((x) => x.enabled_in_bot).map((x) => x.plan_id));
    }
    setModal("bot-manage");
  }

  async function saveBotCatalog() {
    if (!selectedBot) return;
    await run(() => authApi(`/api/v1/bots/${selectedBot.id}/catalog`, {
      method: "PUT",
      body: JSON.stringify({ plan_ids: botCatalogSelection }),
    }), "کاتالوگ ربات ذخیره شد");
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

  async function restoreBackup() {
    if (!backupFile) {
      setError("فایل Backup را انتخاب کنید");
      return;
    }
    if (!window.confirm("Restore به صورت Merge انجام شود؟ داده فعلی حذف نمی‌شود.")) return;
    const fd = new FormData();
    fd.append("backup", backupFile);
    await run(() => authApi("/api/v1/backups/restore", { method: "POST", body: fd }), "Backup بازیابی شد");
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
      <div className="v2Stack">
        <Toolbar search={adminSearch} onSearch={setAdminSearch} placeholder="جستجوی نام کاربری یا نام نماینده">
          <select value={adminStatus} onChange={(e) => setAdminStatus(e.target.value)}>
            <option value="">همه وضعیت‌ها</option>
            <option value="active">فعال</option>
            <option value="disabled">غیرفعال</option>
          </select>
          <button onClick={() => loadAdmins(1)}><SlidersHorizontal size={16} /> اعمال</button>
        </Toolbar>
        <article className="v2Card v2TableCard">
          <div className="v2Table">
            <div className="v2Tr v2Th">
              <span>نماینده</span><span>کلاینت</span><span>کیف پول</span><span>وضعیت</span><span />
            </div>
            {adminsPage.items.map((a) => (
              <div className="v2Tr" key={a.id}>
                <div><strong>{a.display_name || a.username}</strong><small>@{a.username}</small></div>
                <span>{a.client_count.toLocaleString("fa-IR")}</span>
                <span>{money(a.wallet_balance_toman)}</span>
                <span className={a.status === "active" ? "v2Badge ok" : "v2Badge off"}>{a.status}</span>
                <button className="v2More" onClick={() => openAdminManage(a)}><MoreVertical size={18} /></button>
              </div>
            ))}
            {!adminsPage.items.length && <Empty text="نماینده‌ای پیدا نشد." />}
          </div>
          <Pager page={adminsPage.page} pages={adminsPage.pages} total={adminsPage.total} onPage={loadAdmins} />
        </article>
      </div>
    );
  }

  function renderClients() {
    return (
      <div className="v2Stack">
        <Toolbar search={clientSearch} onSearch={setClientSearch} placeholder="جستجو بر اساس Username">
          <select value={clientStatus} onChange={(e) => setClientStatus(e.target.value)}>
            <option value="">همه وضعیت‌ها</option>
            <option value="active">فعال</option>
            <option value="disabled">غیرفعال</option>
            <option value="error">خطا</option>
          </select>
          {user.role === "owner" && (
            <input
              className="v2MiniField"
              placeholder="Admin ID (اختیاری)"
              value={clientAdminFilter}
              onChange={(e) => setClientAdminFilter(e.target.value)}
            />
          )}
          <button onClick={() => loadClients(1)}><SlidersHorizontal size={16} /> اعمال</button>
        </Toolbar>
        <article className="v2Card v2TableCard">
          <div className="v2Table">
            <div className="v2Tr v2Th">
              <span>کلاینت</span><span>نماینده</span><span>مصرف</span><span>حجم</span><span>انقضا</span><span />
            </div>
            {clientsPage.items.map((c) => (
              <div className="v2Tr" key={c.id}>
                <div><strong>{c.username}</strong><small>{c.status} · {c.hwid_limit || "∞"} دستگاه</small></div>
                <span>{c.admin_username || "—"}</span>
                <span>{gib(c.lifetime_usage_bytes)}</span>
                <span>{c.quota_bytes ? gib(c.quota_bytes) : "نامحدود"}</span>
                <span>{dt(c.expires_at)}</span>
                <button className="v2More" onClick={() => { setSelectedId(c.id); setModal("client-manage"); }}><MoreVertical size={18} /></button>
              </div>
            ))}
            {!clientsPage.items.length && <Empty text="کلاینتی پیدا نشد." />}
          </div>
          <Pager page={clientsPage.page} pages={clientsPage.pages} total={clientsPage.total} onPage={loadClients} />
        </article>
      </div>
    );
  }

  function renderPlans() {
    return (
      <div className="v2Grid">
        <article className="v2Card v2Span2">
          <div className="v2CardHead">
            <div><strong>پلن‌ها</strong><span>قیمت پایه Owner و قیمت فروش نماینده</span></div>
          </div>
          <div className="v2PlanGrid">
            {plans.map((p) => (
              <button
                className="v2Plan"
                key={p.id}
                onClick={async () => {
                  setSelectedId(p.id);
                  if (user.role === "owner") await searchAdminOptions("");
                  setAssignmentPrice(p.base_price_per_gib_toman || "");
                  setModal("plan-manage");
                }}
              >
                <div><strong>{p.name}</strong><span className={p.enabled === false ? "v2Badge off" : "v2Badge ok"}>{p.enabled === false ? "خاموش" : "فعال"}</span></div>
                <b>{money(p.retail_price_per_gib_toman || p.base_price_per_gib_toman || p.cost_per_gib_toman)} / GB</b>
                <small>حداکثر: {p.max_quota_gib || "∞"} GB · {p.max_duration_days || "∞"} روز</small>
              </button>
            ))}
            {!plans.length && <Empty text="پلنی تعریف نشده." />}
          </div>
        </article>
        <article className="v2Card">
          <div className="v2CardHead"><div><strong>Groupها</strong><span>Sync شده از PasarGuard</span></div></div>
          <div className="v2Chips">{groups.map((g) => <span key={g.id}>{g.name} · #{g.remote_group_id}</span>)}</div>
        </article>
        <article className="v2Card">
          <div className="v2CardHead"><div><strong>قانون فروش</strong><span>نماینده فقط Plan تخصیص داده‌شده را می‌بیند</span></div></div>
          <div className="v2Info">
            <p>قیمت فروش نماینده نمی‌تواند از قیمت پایه Owner پایین‌تر باشد.</p>
            <p>Billing کیف پول نماینده بر اساس مصرف واقعی Lifetime انجام می‌شود، نه حجم ساخته‌شده.</p>
          </div>
        </article>
      </div>
    );
  }

  function renderWallet() {
    return (
      <div className="v2Stack">
        <section className="v2Metrics">
          <article className="v2Metric v2Balance">
            <span>موجودی کیف پول</span>
            <strong>{money(summary?.wallet_balance_toman)}</strong>
            <small>Ledger منبع اصلی حسابداری است</small>
          </article>
        </section>
        {user.role === "admin" && (
          <article className="v2Card">
            <div className="v2CardHead"><div><strong>شارژ کیف پول</strong><span>درگاه و کارت‌به‌کارت مستقل</span></div></div>
            <div className="v2PaymentActions">
              <button onClick={() => run(async () => {
                const result = await authApi<{ redirect_url: string }>("/api/v1/wallet/topups/gateway", {
                  method: "POST",
                  body: JSON.stringify({ amount_toman: Number(walletTopup) }),
                });
                window.open(result.redirect_url, "_blank", "noopener,noreferrer");
              }, "لینک درگاه ساخته شد")}>زرین‌پال</button>
              <label>
                مبلغ
                <input type="number" value={walletTopup} onChange={(e) => setWalletTopup(e.target.value)} />
              </label>
              <label>
                رسید کارت‌به‌کارت
                <input type="file" accept="image/*,.pdf" onChange={(e) => setWalletReceipt(e.target.files?.[0] || null)} />
              </label>
              <button onClick={() => {
                if (!walletReceipt) return setError("رسید را انتخاب کنید");
                const fd = new FormData();
                fd.append("amount_toman", walletTopup);
                fd.append("receipt", walletReceipt);
                run(() => authApi("/api/v1/wallet/topups/card", { method: "POST", body: fd }), "رسید ارسال شد");
              }}>ارسال رسید کارت</button>
            </div>
          </article>
        )}
        <article className="v2Card v2TableCard">
          <div className="v2CardHead"><div><strong>گردش کیف پول</strong><span>آخرین ۱۰۰ تراکنش</span></div></div>
          <div className="v2Table">
            <div className="v2Tr v2Th"><span>نوع</span><span>مبلغ</span><span>مانده</span><span>تاریخ</span></div>
            {transactions.map((t) => (
              <div className="v2Tr" key={t.id}>
                <div><strong>{t.type}</strong><small>{t.description || "—"}</small></div>
                <span className={Number(t.amount_toman) >= 0 ? "v2Positive" : "v2Negative"}>{money(t.amount_toman)}</span>
                <span>{money(t.balance_after_toman)}</span>
                <span>{dt(t.created_at)}</span>
              </div>
            ))}
          </div>
        </article>
      </div>
    );
  }

  function renderCommerce() {
    return (
      <div className="v2Stack">
        <div className="v2Tabs">
          <button className={commerceTab === "payments" ? "active" : ""} onClick={() => setCommerceTab("payments")}>پرداخت‌ها</button>
          <button className={commerceTab === "orders" ? "active" : ""} onClick={() => setCommerceTab("orders")}>سفارش‌ها</button>
          <button className={commerceTab === "customers" ? "active" : ""} onClick={() => setCommerceTab("customers")}>مشتری‌ها</button>
        </div>

        {commerceTab === "payments" && <>
          <Toolbar search="" onSearch={() => {}} placeholder="پرداخت‌ها">
            <select value={paymentStatus} onChange={(e) => setPaymentStatus(e.target.value)}>
              <option value="">همه وضعیت‌ها</option>
              <option value="pending">pending</option>
              <option value="awaiting_review">awaiting_review</option>
              <option value="paid">paid</option>
              <option value="rejected">rejected</option>
              <option value="failed">failed</option>
            </select>
            <select value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value)}>
              <option value="">همه روش‌ها</option>
              <option value="gateway">درگاه</option>
              <option value="card_to_card">کارت‌به‌کارت</option>
              <option value="customer_wallet">کیف پول مشتری</option>
            </select>
            <button onClick={() => loadPayments(1)}>اعمال</button>
          </Toolbar>
          <article className="v2Card v2TableCard">
            <div className="v2Table">
              <div className="v2Tr v2Th"><span>مبلغ</span><span>روش</span><span>وضعیت</span><span>کاربرد</span><span>تاریخ</span><span /></div>
              {paymentsPage.items.map((p) => (
                <div className="v2Tr" key={p.id}>
                  <strong>{money(p.amount_toman)}</strong>
                  <span>{p.method}</span>
                  <span className={p.status === "paid" ? "v2Badge ok" : p.status === "awaiting_review" ? "v2Badge wait" : "v2Badge"}>{p.status}</span>
                  <span>{p.purpose || "payment"}</span>
                  <span>{dt(p.created_at)}</span>
                  <div className="v2Inline">
                    {p.method === "card_to_card" && <button onClick={() => viewReceipt(p.id)}>رسید</button>}
                    {p.status === "awaiting_review" && (user.role === "owner" || p.purpose !== "admin_wallet_topup") && <>
                      <button className="ok" onClick={() => reviewPayment(p, true)}><Check size={14} /></button>
                      <button className="danger" onClick={() => reviewPayment(p, false)}><X size={14} /></button>
                    </>}
                  </div>
                </div>
              ))}
            </div>
            <Pager page={paymentsPage.page} pages={paymentsPage.pages} total={paymentsPage.total} onPage={loadPayments} />
          </article>
        </>}

        {commerceTab === "orders" && (
          <article className="v2Card v2TableCard">
            <div className="v2Table">
              <div className="v2Tr v2Th"><span>سفارش</span><span>حجم</span><span>مبلغ</span><span>پرداخت</span><span>وضعیت</span></div>
              {ordersPage.items.map((o) => (
                <div className="v2Tr" key={o.id}>
                  <div><strong>{o.id.slice(0, 8)}</strong><small>{dt(o.created_at)}</small></div>
                  <span>{gib(o.quota_bytes)}</span>
                  <span>{money(o.retail_amount_toman)}</span>
                  <span>{o.payment_method}</span>
                  <span className="v2Badge">{o.status}</span>
                </div>
              ))}
            </div>
            <Pager page={ordersPage.page} pages={ordersPage.pages} total={ordersPage.total} onPage={loadOrders} />
          </article>
        )}

        {commerceTab === "customers" && <>
          <Toolbar search={customerSearch} onSearch={setCustomerSearch} placeholder="جستجوی مشتری">
            <button onClick={() => loadCustomers(1)}>جستجو</button>
          </Toolbar>
          <article className="v2Card v2TableCard">
            <div className="v2Table">
              <div className="v2Tr v2Th"><span>مشتری</span><span>Telegram</span><span>کیف پول</span><span>تاریخ عضویت</span></div>
              {customersPage.items.map((c) => (
                <div className="v2Tr" key={c.id}>
                  <div><strong>{c.display_name || c.username || "بدون نام"}</strong><small>@{c.username || "—"}</small></div>
                  <span>{c.telegram_user_id || "—"}</span>
                  <span>{money(c.wallet_balance_toman)}</span>
                  <span>{dt(c.created_at)}</span>
                </div>
              ))}
            </div>
            <Pager page={customersPage.page} pages={customersPage.pages} total={customersPage.total} onPage={loadCustomers} />
          </article>
        </>}
      </div>
    );
  }

  function renderBots() {
    return (
      <article className="v2Card v2TableCard">
        <div className="v2CardHead">
          <div><strong>ربات‌های فروش</strong><span>هر ربات پنل تنظیمات و کاتالوگ مستقل دارد</span></div>
        </div>
        <div className="v2Table">
          <div className="v2Tr v2Th"><span>ربات</span><span>Wallet</span><span>Card</span><span>Gateway</span><span>وضعیت</span><span /></div>
          {bots.map((b) => (
            <div className="v2Tr" key={b.id}>
              <div><strong>{b.name}</strong><small>@{b.username || "—"}</small></div>
              <span>{b.customer_wallet_enabled ? "فعال" : "خاموش"}</span>
              <span>{b.card_to_card_enabled ? "فعال" : "خاموش"}</span>
              <span>{b.gateway_enabled ? "فعال" : "خاموش"}</span>
              <span className={b.enabled ? "v2Badge ok" : "v2Badge off"}>{b.enabled ? "فعال" : "خاموش"}</span>
              <button className="v2More" onClick={() => openBotManage(b)}><MoreVertical size={18} /></button>
            </div>
          ))}
          {!bots.length && <Empty text="رباتی ثبت نشده." />}
        </div>
      </article>
    );
  }

  function renderPasarguard() {
    return (
      <div className="v2Stack">
        <article className="v2Card v2TableCard">
          <div className="v2CardHead"><div><strong>اتصال‌های PasarGuard</strong><span>چند پنل مرکزی قابل اتصال است</span></div></div>
          <div className="v2Table">
            <div className="v2Tr v2Th"><span>نام</span><span>آدرس</span><span>آخرین Sync</span><span>وضعیت</span><span /></div>
            {connections.map((c) => (
              <div className="v2Tr" key={c.id}>
                <div><strong>{c.name}</strong>{c.last_error && <small className="v2Negative">{c.last_error}</small>}</div>
                <span>{c.base_url}</span>
                <span>{dt(c.last_sync_at)}</span>
                <span className={c.enabled ? "v2Badge ok" : "v2Badge off"}>{c.enabled ? "فعال" : "خاموش"}</span>
                <button className="v2More" onClick={() => { setSelectedId(c.id); setModal("connection-manage"); }}><MoreVertical size={18} /></button>
              </div>
            ))}
          </div>
        </article>
      </div>
    );
  }

  function renderReports() {
    return (
      <div className="v2Stack">
        <section className="v2Metrics">
          <article className="v2Metric"><span>فروش</span><strong>{money(financial?.sales_toman)}</strong><small>پرداخت‌های موفق</small></article>
          <article className="v2Metric"><span>هزینه مصرف</span><strong>{money(financial?.actual_usage_cost_toman)}</strong><small>Billing واقعی</small></article>
          <article className="v2Metric"><span>سود ناخالص</span><strong>{money(financial?.gross_margin_toman)}</strong><small>قبل از هزینه‌های جانبی</small></article>
          <article className="v2Metric"><span>سفارش موفق</span><strong>{financial?.provisioned_orders || 0}</strong><small>Provisioned</small></article>
        </section>
        {user.role === "owner" && (
          <article className="v2Card v2TableCard">
            <div className="v2CardHead"><div><strong>Audit Log</strong><span>عملیات حساس سیستم</span></div></div>
            <div className="v2Table">
              <div className="v2Tr v2Th"><span>عملیات</span><span>Entity</span><span>IP</span><span>زمان</span></div>
              {audits.map((a) => (
                <div className="v2Tr" key={a.id}>
                  <strong>{a.action}</strong>
                  <span>{a.entity_type} · {a.entity_id || "—"}</span>
                  <span>{a.ip_address || "—"}</span>
                  <span>{dt(a.created_at)}</span>
                </div>
              ))}
            </div>
          </article>
        )}
      </div>
    );
  }

  function renderSettings() {
    return (
      <div className="v2SettingsGrid">
        <article className="v2Card">
          <div className="v2CardHead">
            <div><strong>کارت‌های بانکی</strong><span>کاملاً جدا از زرین‌پال</span></div>
            <button className="v2PrimarySmall" onClick={() => setModal("bank-card")}><Plus size={15} /> کارت</button>
          </div>
          <div className="v2BankCards">
            {bankCards.map((card) => (
              <div className="v2BankCard" key={card.id}>
                <div><strong>{card.title}</strong>{card.is_default && <span className="v2Badge ok">پیش‌فرض</span>}</div>
                <b>{card.card_number.replace(/(\d{4})(?=\d)/g, "$1 ")}</b>
                <span>{card.card_holder_name || "—"}</span>
                <div className="v2Inline">
                  {!card.is_default && <button onClick={() => run(() => authApi(`/api/v1/bank-cards/${card.id}`, { method: "PATCH", body: JSON.stringify({ is_default: true }) }), "کارت پیش‌فرض شد")}>پیش‌فرض</button>}
                  <button className="danger" onClick={() => run(() => authApi(`/api/v1/bank-cards/${card.id}`, { method: "DELETE" }), "کارت حذف شد")}>حذف</button>
                </div>
              </div>
            ))}
            {!bankCards.length && <Empty text="شماره کارتی ثبت نشده." />}
          </div>
        </article>

        <article className="v2Card">
          <div className="v2CardHead"><div><strong>زرین‌پال</strong><span>درگاه پرداخت مستقل</span></div><CreditCard size={20} /></div>
          <div className="v2Form">
            <label>Merchant ID
              <input
                type="password"
                placeholder={paymentProfile?.gateway_configured ? "برای تغییر Merchant ID وارد کنید" : "Merchant ID زرین‌پال"}
                value={gatewayMerchant}
                onChange={(e) => setGatewayMerchant(e.target.value)}
              />
            </label>
            <label className="v2Check">
              <input
                type="checkbox"
                checked={Boolean(paymentProfile?.gateway_enabled)}
                onChange={(e) => setPaymentProfile((old) => old ? { ...old, gateway_enabled: e.target.checked } : old)}
              />
              درگاه فعال
            </label>
            <button className="v2Primary" onClick={() => run(() => authApi("/api/v1/payment-profile", {
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
        </article>

        <article className="v2Card">
          <div className="v2CardHead"><div><strong>ظاهر پنل</strong><span>Theme و Accent</span></div></div>
          <div className="v2OptionGrid">
            <button className={theme === "dark" ? "active" : ""} onClick={() => setTheme("dark")}>Dark</button>
            <button className={theme === "light" ? "active" : ""} onClick={() => setTheme("light")}>Light</button>
            {(["cyan", "violet", "emerald", "orange"] as const).map((a) => (
              <button key={a} className={accent === a ? "active" : ""} onClick={() => setAccent(a)}>{a}</button>
            ))}
          </div>
        </article>

        {user.role === "owner" && (
          <article className="v2Card">
            <div className="v2CardHead"><div><strong>امنیت Owner</strong><span>2FA و Recovery Code</span></div></div>
            <div className="v2Info">
              <p>2FA: <b>{twoFactor?.enabled ? "فعال" : "غیرفعال"}</b></p>
              <p>Recovery باقی‌مانده: <b>{twoFactor?.recovery_codes_remaining || 0}</b></p>
            </div>
            {!twoFactor?.enabled ? (
              <button className="v2Primary" onClick={() => run(async () => {
                const setup = await authApi<{ secret: string; recovery_codes: string[] }>("/api/v1/security/2fa/setup", { method: "POST" });
                const code = window.prompt(`Secret:\n${setup.secret}\n\nRecovery:\n${setup.recovery_codes.join("  ")}\n\nکد ۶ رقمی:`);
                if (!code) throw new Error("فعال‌سازی لغو شد");
                await authApi("/api/v1/security/2fa/enable", { method: "POST", body: JSON.stringify({ code }) });
              }, "2FA فعال شد")}>فعال‌سازی 2FA</button>
            ) : (
              <button className="v2Danger" onClick={() => {
                const code = window.prompt("کد Authenticator:");
                if (code) run(() => authApi("/api/v1/security/2fa/disable", { method: "POST", body: JSON.stringify({ code }) }), "2FA غیرفعال شد");
              }}>غیرفعال‌کردن 2FA</button>
            )}
          </article>
        )}

        {user.role === "owner" && (
          <article className="v2Card">
            <div className="v2CardHead"><div><strong>Backup & Recovery</strong><span>رمزگذاری‌شده و Merge Restore</span></div></div>
            <div className="v2Form">
              <button onClick={exportBackup}>دانلود Backup</button>
              <label>فایل Restore<input type="file" accept=".pvbackup" onChange={(e) => setBackupFile(e.target.files?.[0] || null)} /></label>
              <button onClick={restoreBackup}>Merge Restore</button>
            </div>
          </article>
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
      <header className={section === "dashboard" ? "v2Topbar primeDashTopbar" : "v2Topbar"}>
        <div className={section === "dashboard" ? "v2Brand primeDashBrand" : "v2Brand"}>
          <div className="v2BrandMark">{section === "dashboard" ? <ShieldCheck size={22} /> : <Gauge size={21} />}</div>
          <div><strong>PRIMEVPN</strong><span>{user.role === "owner" ? "OWNER CONTROL" : "RESELLER PANEL"}</span></div>
        </div>
        <div className={section === "dashboard" ? "v2TopActions primeDashTopActions" : "v2TopActions"}>
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
        <div className="v2DrawerBackdrop" onMouseDown={() => setDrawer(false)}>
          <aside className="v2Drawer" onMouseDown={(e) => e.stopPropagation()}>
            <div className="v2DrawerHead">
              <div>
                <strong>{user.display_name || user.username}</strong>
                <span>{user.role}</span>
              </div>
              <button onClick={() => setDrawer(false)}><X size={19} /></button>
            </div>
            <nav>
              {visibleNav.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.key}
                    className={section === item.key ? "active" : ""}
                    onClick={() => go(item.key)}
                  >
                    <Icon size={19} />
                    <span>{item.label}</span>
                    {item.key === "dashboard" && unread > 0 && <i>{unread}</i>}
                  </button>
                );
              })}
            </nav>
            <button className="v2Logout" onClick={signOut}><LogOut size={18} /> خروج</button>
          </aside>
        </div>
      )}

      <section className="v2Content">
        <div className={section === "dashboard" ? "v2PageHead primeDashPageHead" : "v2PageHead"}>
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

      {canCreate && <button className="v2Fab" onClick={contextualCreate}><Plus size={25} /></button>}

      <Modal open={modal === "admin-create"} title="ساخت نماینده" onClose={() => setModal(null)}>
        <form className="v2Form" onSubmit={createAdmin}>
          <label>نام کاربری<input value={adminForm.username} onChange={(e) => setAdminForm({ ...adminForm, username: e.target.value })} required /></label>
          <label>نام نمایشی<input value={adminForm.display_name} onChange={(e) => setAdminForm({ ...adminForm, display_name: e.target.value })} /></label>
          <label>Telegram ID<input type="number" value={adminForm.telegram_id} onChange={(e) => setAdminForm({ ...adminForm, telegram_id: e.target.value })} /></label>
          <label>رمز عبور<input type="password" minLength={10} value={adminForm.password} onChange={(e) => setAdminForm({ ...adminForm, password: e.target.value })} required /></label>
          <label>موجودی اولیه<input type="number" value={adminForm.initial_balance_toman} onChange={(e) => setAdminForm({ ...adminForm, initial_balance_toman: e.target.value })} /></label>
          <button className="v2Primary" disabled={busy}>ساخت نماینده</button>
        </form>
      </Modal>

      <Modal open={modal === "admin-manage" && Boolean(selectedAdmin)} title={selectedAdmin ? `مدیریت ${selectedAdmin.username}` : "مدیریت نماینده"} onClose={() => setModal(null)} wide>
        {selectedAdmin && <div className="v2Stack">
          <section className="v2Metrics compact">
            <article className="v2Metric"><span>کیف پول</span><strong>{money(selectedAdmin.wallet_balance_toman)}</strong><small>{selectedAdmin.client_count} کلاینت</small></article>
            <article className="v2Metric"><span>وضعیت</span><strong>{selectedAdmin.status}</strong><small>{selectedAdmin.telegram_id || "Telegram ID ندارد"}</small></article>
          </section>
          <article className="v2Card nested">
            <div className="v2CardHead"><div><strong>پلن‌های نماینده</strong><span>{adminAssignments.length} تخصیص</span></div></div>
            <div className="v2Catalog">
              {adminAssignments.map((p) => <div className="v2CatalogRow" key={p.assignment_id}>
                <div><strong>{p.name}</strong><span>{money(p.retail_price_per_gib_toman)} / GB</span></div>
                <button className="danger" onClick={() => run(() => authApi(`/api/v1/admins/${selectedAdmin.id}/plans/${p.plan_id}`, { method: "DELETE" }), "پلن از نماینده حذف شد")}>حذف دسترسی</button>
              </div>)}
              {!adminAssignments.length && <Empty text="پلنی تخصیص داده نشده." />}
            </div>
          </article>
          <div className="v2ActionGrid">
            <button onClick={() => {
              const amount = window.prompt("مبلغ شارژ تومان:");
              if (amount) run(() => authApi(`/api/v1/admins/${selectedAdmin.id}/wallet/topup`, { method: "POST", body: JSON.stringify({ amount_toman: Number(amount), note: "Owner top-up" }) }), "کیف پول شارژ شد");
            }}>شارژ کیف پول</button>
            <button onClick={() => {
              const name = window.prompt("نام نمایشی:", selectedAdmin.display_name || "");
              if (name === null) return;
              const tg = window.prompt("Telegram ID:", selectedAdmin.telegram_id ? String(selectedAdmin.telegram_id) : "");
              const threshold = window.prompt("حد هشدار کیف پول:", selectedAdmin.low_balance_threshold_toman || "0");
              const debt = window.prompt("سقف بدهی:", selectedAdmin.debt_limit_toman || "0");
              const password = window.prompt("رمز جدید (خالی = بدون تغییر):", "");
              run(() => authApi(`/api/v1/admins/${selectedAdmin.id}`, {
                method: "PATCH",
                body: JSON.stringify({
                  display_name: name,
                  telegram_id: tg ? Number(tg) : null,
                  low_balance_threshold_toman: Number(threshold || 0),
                  debt_limit_toman: Number(debt || 0),
                  password: password || null,
                }),
              }), "نماینده ویرایش شد");
            }}>ویرایش مشخصات</button>
            <button className="danger" onClick={() => run(() => authApi(`/api/v1/admins/${selectedAdmin.id}`, {
              method: "PATCH",
              body: JSON.stringify({ status: selectedAdmin.status === "active" ? "disabled" : "active" }),
            }), "وضعیت تغییر کرد")}>{selectedAdmin.status === "active" ? "غیرفعال‌کردن" : "فعال‌کردن"}</button>
          </div>
        </div>}
      </Modal>

      <Modal open={modal === "client-create"} title="ساخت کلاینت" onClose={() => setModal(null)}>
        <form className="v2Form" onSubmit={createClient}>
          <label>Username<input value={clientForm.username} onChange={(e) => setClientForm({ ...clientForm, username: e.target.value })} required /></label>
          {user.role === "owner" && <div className="v2Picker">
            <label>جستجوی نماینده
              <div className="v2PickerSearch"><input value={adminPickerSearch} onChange={(e) => setAdminPickerSearch(e.target.value)} placeholder="نام کاربری یا نام نماینده" /><button type="button" onClick={() => searchAdminOptions()}>جستجو</button></div>
            </label>
            <label>نماینده
              <select value={clientForm.admin_id} onChange={(e) => chooseClientAdmin(e.target.value)} required>
                <option value="">انتخاب نماینده</option>
                {adminOptions.map((a) => <option key={a.id} value={a.id}>{a.display_name || a.username} (@{a.username})</option>)}
              </select>
            </label>
          </div>}
          <label>پلن<select value={clientForm.plan_id} onChange={(e) => setClientForm({ ...clientForm, plan_id: e.target.value })} required><option value="">انتخاب پلن</option>{(user.role === "owner" ? clientPlanOptions : plans).filter((p) => p.enabled !== false).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          <label>حجم GB<input type="number" step="0.1" value={clientForm.quota_gib} onChange={(e) => setClientForm({ ...clientForm, quota_gib: e.target.value })} required /></label>
          <label>مدت روز<input type="number" value={clientForm.duration_days} onChange={(e) => setClientForm({ ...clientForm, duration_days: e.target.value })} /></label>
          <label>تعداد دستگاه<input type="number" value={clientForm.hwid_limit} onChange={(e) => setClientForm({ ...clientForm, hwid_limit: e.target.value })} /></label>
          <button className="v2Primary" disabled={busy}>ساخت کلاینت</button>
        </form>
      </Modal>

      <Modal open={modal === "client-manage" && Boolean(selectedClient)} title={selectedClient ? selectedClient.username : "کلاینت"} onClose={() => setModal(null)} wide>
        {selectedClient && <div className="v2Stack">
          <section className="v2Metrics compact">
            <article className="v2Metric"><span>مصرف</span><strong>{gib(selectedClient.lifetime_usage_bytes)}</strong><small>Lifetime</small></article>
            <article className="v2Metric"><span>حجم</span><strong>{selectedClient.quota_bytes ? gib(selectedClient.quota_bytes) : "∞"}</strong><small>{selectedClient.hwid_limit || "∞"} دستگاه</small></article>
            <article className="v2Metric"><span>انقضا</span><strong>{dt(selectedClient.expires_at)}</strong><small>{selectedClient.status}</small></article>
          </section>
          {selectedClient.subscription_url && <div className="v2QrInline">
            <QRCodeSVG value={selectedClient.subscription_url} size={150} />
            <div><strong>Subscription</strong><span>{selectedClient.subscription_url}</span><button onClick={() => navigator.clipboard.writeText(selectedClient.subscription_url || "")}><Copy size={14} /> کپی</button></div>
          </div>}
          <div className="v2ActionGrid">
            <button onClick={() => {
              const quota = window.prompt("حجم جدید GB (خالی = تغییر نکند):", "");
              const days = window.prompt("تمدید از امروز چند روز؟ (خالی = تغییر نکند):", "");
              const hwid = window.prompt("تعداد دستگاه (خالی = تغییر نکند):", "");
              run(() => authApi(`/api/v1/clients/${selectedClient.id}`, {
                method: "PATCH",
                body: JSON.stringify({
                  quota_gib: quota ? Number(quota) : null,
                  duration_days_from_now: days ? Number(days) : null,
                  hwid_limit: hwid ? Number(hwid) : null,
                }),
              }), "کلاینت ویرایش شد");
            }}>ویرایش حجم/مدت/HWID</button>
            <button onClick={() => run(() => authApi(`/api/v1/clients/${selectedClient.id}/reset-usage`, { method: "POST" }), "مصرف Reset شد")}>Reset Usage</button>
            <button onClick={() => run(() => authApi(`/api/v1/clients/${selectedClient.id}/revoke-subscription`, { method: "POST" }), "Subscription عوض شد")}>Revoke Subscription</button>
            <button className="danger" onClick={() => run(() => authApi(`/api/v1/clients/${selectedClient.id}`, {
              method: "PATCH",
              body: JSON.stringify({ disabled: selectedClient.status === "active" }),
            }), "وضعیت تغییر کرد")}>{selectedClient.status === "active" ? "Disable" : "Enable"}</button>
          </div>
        </div>}
      </Modal>

      <Modal open={modal === "plan-create"} title="ساخت پلن پایه" onClose={() => setModal(null)}>
        <form className="v2Form" onSubmit={createPlan}>
          <label>نام پلن<input value={planForm.name} onChange={(e) => setPlanForm({ ...planForm, name: e.target.value })} required /></label>
          <label>Group<select value={planForm.group_id} onChange={(e) => setPlanForm({ ...planForm, group_id: e.target.value })} required><option value="">انتخاب Group</option>{groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
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
          <div className="v2Info">
            <p>قیمت پایه: <b>{money(selectedPlan.base_price_per_gib_toman || selectedPlan.cost_per_gib_toman)} / GB</b></p>
            <p>قیمت فروش: <b>{money(selectedPlan.retail_price_per_gib_toman || selectedPlan.base_price_per_gib_toman)} / GB</b></p>
          </div>
          {user.role === "owner" ? <>
            <div className="v2AssignBox">
              <strong>تخصیص این پلن به نماینده</strong>
              <div className="v2PickerSearch"><input value={adminPickerSearch} onChange={(e) => setAdminPickerSearch(e.target.value)} placeholder="جستجوی نماینده" /><button onClick={() => searchAdminOptions()}>جستجو</button></div>
              <select value={clientForm.admin_id} onChange={(e) => setClientForm({ ...clientForm, admin_id: e.target.value })}>
                <option value="">انتخاب نماینده</option>
                {adminOptions.map((a) => <option key={a.id} value={a.id}>{a.display_name || a.username} (@{a.username})</option>)}
              </select>
              <input type="number" placeholder="قیمت فروش هر GB" value={assignmentPrice} onChange={(e) => setAssignmentPrice(e.target.value)} />
              <button className="v2Primary" onClick={() => run(() => authApi(`/api/v1/admins/${clientForm.admin_id}/plans/${selectedPlan.id}`, { method: "PUT", body: JSON.stringify({ retail_price_per_gib_toman: Number(assignmentPrice), bot_visible: true }) }), "پلن به نماینده تخصیص داده شد")}>تخصیص پلن</button>
            </div>
            <button onClick={() => {
              const name = window.prompt("نام پلن:", selectedPlan.name);
              const price = window.prompt("قیمت پایه هر GB:", selectedPlan.base_price_per_gib_toman || "");
              if (name && price) run(() => authApi(`/api/v1/plans/${selectedPlan.id}`, { method: "PATCH", body: JSON.stringify({ name, base_price_per_gib_toman: Number(price) }) }), "پلن ویرایش شد");
            }}>ویرایش پلن</button>
            <button className="v2Danger" onClick={() => run(() => authApi(`/api/v1/plans/${selectedPlan.id}`, { method: "DELETE" }), "پلن خاموش شد")}>خاموش‌کردن پلن</button>
          </> : <button onClick={() => {
            const price = window.prompt("قیمت فروش هر GB:", selectedPlan.retail_price_per_gib_toman || "");
            if (price) run(() => authApi(`/api/v1/my-plans/${selectedPlan.id}/retail-price`, { method: "PATCH", body: JSON.stringify({ retail_price_per_gib_toman: Number(price) }) }), "قیمت فروش ذخیره شد");
          }}>تغییر قیمت فروش</button>}
        </div>}
      </Modal>

      <Modal open={modal === "connection-create"} title="افزودن PasarGuard" onClose={() => setModal(null)}>
        <form className="v2Form" onSubmit={createConnection}>
          <label>نام اتصال<input value={connectionForm.name} onChange={(e) => setConnectionForm({ ...connectionForm, name: e.target.value })} required /></label>
          <label>Panel URL<input placeholder="https://panel.example.com" value={connectionForm.base_url} onChange={(e) => setConnectionForm({ ...connectionForm, base_url: e.target.value })} required /></label>
          <label>API Token<input type="password" value={connectionForm.api_token} onChange={(e) => setConnectionForm({ ...connectionForm, api_token: e.target.value })} required /></label>
          <button className="v2Primary">تست و اضافه‌کردن</button>
        </form>
      </Modal>

      <Modal open={modal === "connection-manage" && Boolean(selectedConnection)} title={selectedConnection?.name || "PasarGuard"} onClose={() => setModal(null)}>
        {selectedConnection && <div className="v2ActionGrid">
          <button onClick={() => run(() => authApi(`/api/v1/connections/${selectedConnection.id}/test`, { method: "POST" }), "اتصال سالم است")}>Test Connection</button>
          <button onClick={() => run(() => authApi(`/api/v1/connections/${selectedConnection.id}/sync-groups`, { method: "POST" }), "Groupها Sync شدند")}>Sync Groups</button>
          <button onClick={() => {
            const name = window.prompt("نام اتصال:", selectedConnection.name);
            const url = window.prompt("URL:", selectedConnection.base_url);
            const token = window.prompt("Token جدید (خالی = بدون تغییر):", "");
            if (name && url) run(() => authApi(`/api/v1/connections/${selectedConnection.id}`, {
              method: "PATCH",
              body: JSON.stringify({ name, base_url: url, api_token: token || null, enabled: true }),
            }), "اتصال ویرایش شد");
          }}>ویرایش اتصال</button>
          <button className="v2Danger" onClick={() => run(() => authApi(`/api/v1/connections/${selectedConnection.id}`, { method: "DELETE" }), "اتصال غیرفعال شد")}>Disable</button>
        </div>}
      </Modal>

      <Modal open={modal === "bot-create"} title="ساخت ربات فروش" onClose={() => setModal(null)}>
        <form className="v2Form" onSubmit={createBot}>
          <label>نام ربات<input value={botForm.name} onChange={(e) => setBotForm({ ...botForm, name: e.target.value })} required /></label>
          <label>Bot Token<input type="password" value={botForm.token} onChange={(e) => setBotForm({ ...botForm, token: e.target.value })} required /></label>
          {user.role === "owner" && <div className="v2Picker">
            <label>جستجوی نماینده
              <div className="v2PickerSearch"><input value={adminPickerSearch} onChange={(e) => setAdminPickerSearch(e.target.value)} placeholder="نام کاربری نماینده" /><button type="button" onClick={() => searchAdminOptions()}>جستجو</button></div>
            </label>
            <label>نماینده
              <select value={botForm.admin_id} onChange={(e) => setBotForm({ ...botForm, admin_id: e.target.value })} required>
                <option value="">انتخاب نماینده</option>
                {adminOptions.map((a) => <option key={a.id} value={a.id}>{a.display_name || a.username} (@{a.username})</option>)}
              </select>
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
            <article className="v2Metric"><span>Username</span><strong>@{selectedBot.username || "—"}</strong><small>{selectedBot.enabled ? "فعال" : "خاموش"}</small></article>
            <article className="v2Metric"><span>روش‌های پرداخت</span><strong>{[selectedBot.customer_wallet_enabled && "Wallet", selectedBot.card_to_card_enabled && "Card", selectedBot.gateway_enabled && "Gateway"].filter(Boolean).join(" + ") || "هیچ"}</strong><small>قابل تغییر</small></article>
          </section>
          <div className="v2ActionGrid">
            <button onClick={() => run(() => authApi(`/api/v1/bots/${selectedBot.id}`, { method: "PATCH", body: JSON.stringify({ customer_wallet_enabled: !selectedBot.customer_wallet_enabled }) }), "Wallet تغییر کرد")}>Wallet {selectedBot.customer_wallet_enabled ? "ON" : "OFF"}</button>
            <button onClick={() => run(() => authApi(`/api/v1/bots/${selectedBot.id}`, { method: "PATCH", body: JSON.stringify({ card_to_card_enabled: !selectedBot.card_to_card_enabled }) }), "Card تغییر کرد")}>Card {selectedBot.card_to_card_enabled ? "ON" : "OFF"}</button>
            <button onClick={() => run(() => authApi(`/api/v1/bots/${selectedBot.id}`, { method: "PATCH", body: JSON.stringify({ gateway_enabled: !selectedBot.gateway_enabled }) }), "Gateway تغییر کرد")}>Gateway {selectedBot.gateway_enabled ? "ON" : "OFF"}</button>
            <button onClick={() => {
              const name = window.prompt("نام ربات:", selectedBot.name);
              const token = window.prompt("Token جدید (خالی = بدون تغییر):", "");
              if (name) run(() => authApi(`/api/v1/bots/${selectedBot.id}`, { method: "PATCH", body: JSON.stringify({ name, token: token || null }) }), "ربات ویرایش شد");
            }}>نام / Token</button>
            <button className="v2Danger" onClick={() => run(() => authApi(`/api/v1/bots/${selectedBot.id}`, { method: "DELETE" }), "ربات خاموش شد")}>خاموش‌کردن</button>
          </div>
          <article className="v2Card nested">
            <div className="v2CardHead"><div><strong>کاتالوگ همین ربات</strong><span>فقط پلن‌های انتخاب‌شده در این Bot نمایش داده می‌شوند</span></div></div>
            <div className="v2Catalog">
              {botCatalog.map((p) => (
                <label key={p.plan_id}>
                  <input
                    type="checkbox"
                    checked={botCatalogSelection.includes(p.plan_id)}
                    onChange={(e) => setBotCatalogSelection((old) =>
                      e.target.checked ? [...old, p.plan_id] : old.filter((id) => id !== p.plan_id)
                    )}
                  />
                  <div><strong>{p.name}</strong><span>{money(p.retail_price_per_gib_toman)} / GB</span></div>
                </label>
              ))}
            </div>
            <button className="v2Primary" onClick={saveBotCatalog}>ذخیره کاتالوگ ربات</button>
          </article>
        </div>}
      </Modal>

      <Modal open={modal === "bank-card"} title="افزودن کارت بانکی" onClose={() => setModal(null)}>
        <form className="v2Form" onSubmit={createCard}>
          <label>عنوان کارت<input value={cardForm.title} onChange={(e) => setCardForm({ ...cardForm, title: e.target.value })} /></label>
          <label>شماره کارت<input inputMode="numeric" placeholder="603799..." value={cardForm.card_number} onChange={(e) => setCardForm({ ...cardForm, card_number: e.target.value })} required /></label>
          <label>نام صاحب کارت<input value={cardForm.card_holder_name} onChange={(e) => setCardForm({ ...cardForm, card_holder_name: e.target.value })} /></label>
          <label>توضیحات<input value={cardForm.instructions} onChange={(e) => setCardForm({ ...cardForm, instructions: e.target.value })} /></label>
          <label className="v2Check"><input type="checkbox" checked={cardForm.is_default} onChange={(e) => setCardForm({ ...cardForm, is_default: e.target.checked })} /> کارت پیش‌فرض</label>
          <button className="v2Primary">ذخیره کارت</button>
        </form>
      </Modal>
    </main>
  );
}
