---
name: pasarguard-manager
description: Manage the user's PasarGuard panel through AFZONE-AI, including admins/resellers, users/clients, groups, hosts, nodes, cores, templates, roles, usage, settings, and operational actions.
---

# PasarGuard Manager

Use AFZONE-AI MCP tools as the control plane for PasarGuard. PasarGuard itself is not modified.

## Safety and mutations

Read operations can run immediately. For every create, update, reset, reconnect, revoke, settings change, or delete:

1. Read the current object first when practical.
2. Summarize the exact intended change and important before/after values.
3. Ask the user for explicit confirmation.
4. Call the mutation again with `confirm=true` only after confirmation.

Never treat an earlier unrelated confirmation as approval for a new mutation.

## Core resources

Use `list_resource`, `get_resource`, `create_resource`, `update_resource`, and `delete_resource` with:

- `admins`
- `users`
- `groups`
- `hosts`
- `nodes`
- `cores`
- `user_templates`
- `client_templates`
- `admin_roles`
- `api_keys`

Use `run_action` for:

- admins: `reset_usage`, `disable_users`, `activate_users`, `delete_users`
- users: `reset_usage`, `revoke_subscription`, `activate_next_plan`
- nodes: `reset_usage`, `reconnect`, `sync`, `update_core`, `realtime_stats`, `stats`, `outbounds_latency`
- cores: `restart`
- api_keys: `revoke`

Use `get_panel_info` for settings, system, inbounds, WireGuard subnet usage, and worker health.
Use `update_settings` for settings mutations.

## Full API escape hatch

`panel_request` can call operational `/api/*` endpoints not covered by convenience tools. It blocks setup/login endpoints. GET requests are read-only. POST/PUT/PATCH/DELETE require `confirm=true`.

## Traffic semantics

For admins/resellers, `data_limit` is the assigned quota and `used_traffic` is current consumed traffic. Calculate remaining finite quota as `max(data_limit - used_traffic, 0)`. A null/non-positive data limit is treated as unlimited unless the live response indicates otherwise.

Do not invent byte conversions. State whether displayed values are decimal GB/TB or binary GiB/TiB when converting.
