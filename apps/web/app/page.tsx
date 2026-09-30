import {
  Activity,
  Bot,
  Boxes,
  CircleDollarSign,
  Gauge,
  LayoutDashboard,
  Server,
  Settings,
  ShieldCheck,
  Users,
  WalletCards
} from "lucide-react";

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
  [Settings, "تنظیمات"]
] as const;

const cards = [
  ["موجودی نمایندگان", "۰ تومان", "+۰٪"],
  ["مصرف امروز", "۰ GiB", "Live billing"],
  ["فروش امروز", "۰ تومان", "۰ سفارش"],
  ["کلاینت‌های فعال", "۰", "۰ آنلاین"]
];

export default function Home() {
  return (
    <main className="shell">
      <aside className="sidebar glass">
        <div className="brand">
          <div className="brandMark"><Gauge size={25} /></div>
          <div><strong>PRIMEVPN</strong><span>Control Center</span></div>
        </div>

        <nav>
          {nav.map(([Icon, label], index) => (
            <button className={index === 0 ? "navItem active" : "navItem"} key={label}>
              <Icon size={19}/><span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="ownerCard">
          <div className="avatar">P</div>
          <div><strong>مالک سیستم</strong><span>Owner</span></div>
          <div className="onlineDot"/>
        </div>
      </aside>

      <section className="workspace">
        <header>
          <div>
            <p className="eyebrow">PRIME NETWORK · LIVE</p>
            <h1>مرکز کنترل PRIMEVPN</h1>
            <p className="muted">فروش، مصرف، کیف پول و زیرساخت در یک داشبورد</p>
          </div>
          <div className="headerActions">
            <button className="ghost">همگام‌سازی</button>
            <button className="primary">+ نماینده جدید</button>
          </div>
        </header>

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
              <div><h2>مصرف و Billing</h2><p>کسر کیف پول بر اساس مصرف واقعی Lifetime</p></div>
              <span className="live"><i/> LIVE</span>
            </div>
            <div className="chart">
              {[40,63,48,76,58,84,71,92,68,88,75,96].map((height, i) => (
                <div className="bar" key={i}><span style={{height: height + "%"}}/></div>
              ))}
            </div>
            <div className="chartLabels"><span>۰۰:۰۰</span><span>۰۶:۰۰</span><span>۱۲:۰۰</span><span>۱۸:۰۰</span><span>اکنون</span></div>
          </article>

          <article className="panel">
            <div className="panelHead"><div><h2>وضعیت سیستم</h2><p>سرویس‌های اصلی</p></div></div>
            {["API PRIMEVPN","PostgreSQL","Redis / Worker","PasarGuard"].map((x, i) => (
              <div className="statusRow" key={x}>
                <span><i className={i === 3 ? "dot amber" : "dot"}/>{x}</span>
                <b>{i === 3 ? "منتظر اتصال" : "آماده"}</b>
              </div>
            ))}
          </article>

          <article className="panel">
            <div className="panelHead"><div><h2>کیف پول و هشدارها</h2><p>کنترل ریسک نمایندگان</p></div></div>
            <div className="emptyState">
              <WalletCards size={42}/>
              <strong>هنوز نماینده‌ای ساخته نشده</strong>
              <span>بعد از ساخت نماینده، موجودی و هشدار کمبود اعتبار اینجا نمایش داده می‌شود.</span>
            </div>
          </article>

          <article className="panel wide">
            <div className="panelHead"><div><h2>آخرین فعالیت‌ها</h2><p>Audit log تغییرات حساس</p></div></div>
            <div className="activityTable">
              <div><b>سیستم</b><span>هسته PRIMEVPN آماده‌سازی شد</span><time>اکنون</time></div>
              <div><b>Billing</b><span>محاسبه بر اساس Lifetime Usage فعال است</span><time>آماده</time></div>
              <div><b>Security</b><span>Secretها به‌صورت رمزگذاری‌شده ذخیره می‌شوند</span><time>آماده</time></div>
            </div>
          </article>
        </section>
      </section>
    </main>
  );
}
