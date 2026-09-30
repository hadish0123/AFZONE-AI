# PRIMEVPN architecture

## Roles

### Owner
The platform owner. Has access to every connection, admin, group, plan, wallet, payment, client, bot, report and setting.

### Admin
A reseller. Has an isolated panel and can only use groups/plans allowed by the owner. An admin can:
- manage their own clients;
- choose from owner-approved groups/plans;
- set retail prices above their assigned cost;
- manage their own Telegram bot;
- manage their customer payments and customer wallets;
- inspect their own sales, usage and wallet ledger.

An Admin cannot change owner base pricing, enable an unassigned group, edit another admin, or access owner secrets.

## PasarGuard connections

A connection contains:
- display name;
- base URL;
- encrypted API token;
- status and last sync timestamp.

On sync, PRIMEVPN imports PasarGuard groups as local read-through records. Owner pricing and reseller eligibility are maintained only in PRIMEVPN.

## Plans and pricing

A Plan targets exactly one PasarGuard connection and group for V1.

Owner controls:
- enabled state;
- base price per GiB;
- optional min/max quota;
- optional max duration;
- device/HWID limits;
- admin eligibility.

Admin controls:
- retail price presented to their own customers;
- visibility in their own Telegram bot.

Admin retail price cannot be lower than owner cost unless owner explicitly permits it later.

## Wallets

Each Admin has one wallet.

Wallet balance is a cached balance. The ledger is authoritative.

Transaction categories include:
- owner_topup
- gateway_topup
- card_topup
- usage_charge
- refund
- bonus
- adjustment

Every transaction includes:
- amount;
- resulting balance;
- reference type/id;
- idempotency key;
- actor;
- timestamp.

Usage charges are never inferred from created quota. They are calculated from actual PasarGuard lifetime traffic delta.

## Billing

A UsageCheckpoint is maintained per PRIMEVPN client.

Preferred counter:
- PasarGuard lifetime usage.

Algorithm:
1. Sync current lifetime usage.
2. Compare with last billed lifetime usage.
3. Ignore duplicate/older snapshots.
4. Calculate positive delta bytes.
5. Snapshot the applicable owner price.
6. Write a BillingEvent.
7. Debit Admin wallet atomically.
8. Advance checkpoint only inside the same database transaction.

If PasarGuard reports a lower lifetime counter than the checkpoint, billing is suspended for that client and an anomaly is raised rather than silently under/over-charging.

## Low balance policy

V1 supports configurable thresholds:
- warning threshold;
- block new client creation;
- block renewals;
- optional debt limit.

Existing clients are not automatically disabled merely because a wallet reached zero unless Owner explicitly enables a suspension policy.

## Customer sales

A customer order is separate from the Admin's cost.

Example:
- Owner cost = 1,000 Toman/GiB.
- Admin retail price = 2,000 Toman/GiB.
- Customer buys a 100 GiB product.
- Customer payment belongs to the Admin's sales ledger.
- Admin cost to Owner is still charged from actual usage, not the 100 GiB provisioned limit.

## Payment methods

Customer checkout supports:
- customer wallet;
- payment gateway;
- card-to-card.

Admin wallet top-up supports:
- owner manual credit;
- payment gateway;
- card-to-card receipt + approval.

Gateway implementation is adapter-based so a concrete provider can be selected without changing domain logic.

## Telegram

Each Admin can register one or more bots. Bot tokens are encrypted at rest.
Bots only display products assigned by Owner and enabled by that Admin.
Bots call PRIMEVPN API; they never receive PasarGuard API tokens.

## Audit

All sensitive mutations must create an audit event with actor, action, entity, request metadata and before/after JSON where safe. Secrets are redacted.
