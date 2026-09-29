# AFZONE-AI

Private ChatGPT/MCP control plane for PasarGuard. This repository is intentionally separate from PasarGuard and PasarGuard-Node; it does not patch either project.

## Architecture

```text
ChatGPT Plugin
      |
      v
AFZONE-AI MCP Gateway (Railway)
      |
      | X-Api-Key
      v
PasarGuard Central API
      |
      v
PasarGuard Nodes / Xray
```

## Current scope

- Full operational access to PasarGuard `/api/*` through a guarded generic tool
- CRUD helpers for admins, users, groups, hosts, nodes, cores, templates, roles, and API-key metadata
- Node actions and health/statistics
- Settings and system information
- Explicit confirmation required for every mutation
- Authentication/setup endpoints intentionally blocked
- Sensitive fields redacted from tool responses
- Railway-ready Streamable HTTP MCP endpoint at `/mcp`

## Local configuration

Copy `.env.example` to `.env` and set:

- `PASARGUARD_BASE_URL`
- `PASARGUARD_API_KEY`
- `AFZONE_GATEWAY_TOKEN`
- `REQUEST_TIMEOUT_SECONDS`

Never commit real credentials.

## Run

```bash
pip install -e '.[dev]'
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check: `GET /health`
MCP endpoint: `/mcp`

## ChatGPT plugin package

`plugin/` contains the private plugin manifest and PasarGuard management skill. After Railway deployment, copy `plugin/mcp.json.example` to `plugin/mcp.json` and replace the placeholder with the generated HTTPS Railway domain. Authentication is configured at connection time; secrets must never be embedded in `mcp.json`.
