# AFZONE-AI

Private ChatGPT integration and business gateway for PasarGuard.

## Architecture

ChatGPT Plugin / MCP
→ AFZONE-AI Gateway
→ PasarGuard REST API
→ PasarGuard Nodes

PasarGuard itself remains unchanged.

## Initial scope

- Read-only PasarGuard connectivity
- Reseller/admin listing and lookup
- Quota/usage summaries
- Node listing and health data
- Railway-ready deployment
- Secrets only via environment variables

Mutation tools (create admin, quota changes, reset usage, enable/disable) will be added after read-only connectivity is verified.

## Environment

Copy `.env.example` and configure values in Railway. Never commit real API keys.
