# AFZONE-AI

Private ChatGPT/MCP control plane for PasarGuard. This project is separate from PasarGuard and PasarGuard-Node and does not patch either codebase.

## Architecture

```text
ChatGPT Plugin
      |
      | OAuth 2.1 + PKCE
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

## Capabilities

- Full operational access to PasarGuard `/api/*` through a guarded generic tool
- CRUD helpers for admins, users, groups, hosts, nodes, cores, templates, roles, and API-key metadata
- Node actions, usage, health and statistics
- Settings and system operations
- Explicit confirmation required for every mutation
- Setup/login endpoints intentionally blocked
- Sensitive values redacted from MCP tool responses
- OAuth 2.1 authorization for ChatGPT with dynamic client registration and PKCE
- Railway-ready Streamable HTTP MCP endpoint at `/mcp`

## Environment

Configure these values only in Railway or a local `.env` file. Never commit real credentials.

- `PASARGUARD_BASE_URL`
- `PASARGUARD_API_KEY`
- `AFZONE_PUBLIC_URL`
- `AFZONE_OAUTH_USERNAME`
- `AFZONE_OAUTH_PASSWORD`
- `AFZONE_OAUTH_SCOPE`
- `REQUEST_TIMEOUT_SECONDS`

`AFZONE_OAUTH_PASSWORD` is the password used when connecting ChatGPT to this private plugin. It is independent of both the PasarGuard owner password and PasarGuard API key.

## Run

```bash
pip install -e '.[dev]'
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Health: `GET /health`
- PasarGuard connectivity: `GET /pasarguard_health`
- MCP: `/mcp`
- OAuth metadata and endpoints are exposed by the MCP SDK on the same host.

## ChatGPT plugin

`plugin/` contains the private Agent Plugin package. Its `mcp.json` points to the deployed Railway MCP endpoint and contains no secrets. Authentication is completed through OAuth when the plugin is connected in ChatGPT.
