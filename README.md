# PRIMEVPN

PRIMEVPN is a commercial control plane built on top of PasarGuard. PasarGuard stays untouched and remains the technical source of truth for VPN users, groups, traffic and subscriptions. PRIMEVPN adds the business layer: owners, admins/resellers, wallets, pricing, plans, real-usage billing, Telegram sales bots, payments, reports and audit logs.

## V1 scope

- Owner and Admin roles only
- Multiple PasarGuard connections via panel URL + API token
- Group sync from PasarGuard
- Owner-defined base pricing per GiB and allowed groups
- Admin/reseller wallet with immutable ledger
- Charge admins from real lifetime traffic usage, not provisioned quota
- Client CRUD with quota, expiry, HWID/device limit and group assignment
- Plans and reseller-specific retail prices
- Telegram bot per admin
- Customer wallet, payment gateway, and card-to-card payment flows
- Sales/orders, receipts and financial reports
- Audit logs, notifications, low-balance rules and billing safeguards
- Responsive premium web dashboard with light/dark themes

## Architecture

```
Browser / Telegram
        |
        v
PRIMEVPN Web + API
        |
        +---- PostgreSQL
        +---- Redis / workers
        +---- Payment adapters
        |
        v
PasarGuard REST API
```

PRIMEVPN never modifies PasarGuard or PasarGuard-Node source code.

## Monorepo

- `apps/api` - FastAPI API, billing engine, PasarGuard adapter, Telegram/payment services
- `apps/web` - Next.js dashboard
- `docs` - architecture and domain documentation

## Money and traffic

Money is stored as NUMERIC amounts denominated in **Toman**.
Traffic is stored in **bytes**. Display conversion uses GiB/TiB unless explicitly labelled otherwise.

Billing uses PasarGuard lifetime traffic counters whenever available:

`delta = current_lifetime_usage - last_billed_lifetime_usage`

`charge = delta_bytes / 2^30 * base_price_per_GiB`

Every wallet mutation is represented by an immutable ledger entry with an idempotency key.
