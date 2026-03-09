# Vintage Resale MCP — Onboarding Guide

**Audience:** Human engineers and AI agents. Both should be fully operational after reading this.

**Project:** `vintage-resale-mcp` — a production Model Context Protocol server for a vintage resale marketplace. Built on a generic `mcp-saas-template`, customized for vintage resale domain logic with billing, passive signal capture, and web price enrichment.

---

## Table of Contents

1. [What MCP Is](#1-what-mcp-is)
2. [Architecture](#2-architecture)
3. [The Data Flywheel](#3-the-data-flywheel)
4. [File-by-File Reference](#4-file-by-file-reference)
5. [The 8 Vintage Resale Tools](#5-the-8-vintage-resale-tools)
6. [How to Add a New Tool](#6-how-to-add-a-new-tool)
7. [Configuration Reference](#7-configuration-reference)
8. [Deployment Guide](#8-deployment-guide)
9. [Registering in Claude Desktop](#9-registering-in-claude-desktop)
10. [HTTP API Reference](#10-http-api-reference)
11. [Current State vs. Planned Features](#11-current-state-vs-planned-features)
12. [For AI Agents](#12-for-ai-agents)

---

## 1. What MCP Is

MCP (Model Context Protocol) is a standard for AI models to call external tools. Think of it as an API, but designed specifically for AI agents.

Instead of a human browser calling REST endpoints, an AI model (Claude, ChatGPT, etc.) sends JSON-RPC messages like:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "search_inventory",
    "arguments": { "query": "1970s Levi's denim", "category": "clothing" }
  }
}
```

The MCP server executes the tool and returns a structured result. The AI model sees the result and incorporates it into its response to the user.

**Two transport modes:**

- **SSE (Server-Sent Events):** Client connects over HTTP to `/sse`, receives a session ID, then POSTs messages to `/message?sessionId=<id>`. Used for remote deployments. The server pushes responses back over the SSE stream.
- **stdio:** Server reads JSON-RPC from stdin, writes responses to stdout. Used for local Claude Desktop integration (`python server.py --stdio`).

This server supports both, switchable at startup.

---

## 2. Architecture

```
AI Client (Claude, ChatGPT, etc.)
    |  JSON-RPC over SSE (remote) or stdio (local)
    v
server.py  --  MCP Protocol Handler
    |  Receives tool calls, extracts API key, routes to billing middleware
    v
billing.py  --  Billing Middleware (create_billing_middleware)
    |  1. API key validation (validate_api_key)
    |  2. Rate limiting (check_rate_limit, sliding 60-second window)
    |  3. Free tier enforcement (check_free_tier, 100 calls/month default)
    |  4. Calls the actual tool handler
    |  5. Records usage + Stripe metering (record_usage)
    v
Tool Handler  --  tools/resale.py  [PLANNED — see section 11]
    |  Executes vintage resale domain logic
    |  Reads from /data/inventory/ (local JSON store)
    |  Reads from /data/signals/ (demand signal store)
    v
Serper Enrichment  --  middleware/serper_connector.py  [PLANNED]
    |  Silently enriches price comp results with live eBay/Etsy data
    |  24-hour response cache (avoids per-call Serper costs)
    v
Response  -->  AI Client
    |
    └──> Signal Capture  --  middleware/signal_capture.py  [PLANNED]
              Non-blocking, fires after response is sent
              Records: query, category, user, timestamp, result metadata
              Writes to /data/signals/signals.json
              Powers trending_now and price intelligence
```

**Currently implemented (live in the repo):**

- `server.py` — full MCP protocol, SSE + stdio transports, consumer HTTP routes
- `billing.py` — API key CRUD, rate limiting, free tier, Stripe metering, affiliate commissions
- `config.py` — environment-based configuration singleton
- `tools/example.py` — three template tools (`echo`, `hello_world`, `get_status`)
- `tools/__init__.py` — tool registry aggregator
- `strategy/competitor_analysis.py` — pricing benchmark engine

**Planned but not yet implemented:** `tools/resale.py`, `middleware/` directory, signal store, Serper integration. See section 11.

---

## 3. The Data Flywheel

The core business moat: every tool call generates data that makes future tool calls more accurate.

**How it works:**

1. A buyer searches "1970s Levi's" — `search_inventory` is called.
2. Signal captured: `{term: "1970s Levi's", category: "clothing", timestamp: ..., user_id: ...}`
3. Another buyer calls `trending_now` — sees "1970s Levi's" trending because of real search volume in the signal store. Zero external API calls needed.
4. A seller calls `get_price_comps` for "1970s Levi's 501" — gets real comps from Serper (live eBay/Etsy) plus locally recorded sold prices.
5. Seller lists at the right price, item sells. `mark_sold` is called with the actual transaction price.
6. That sold price enters the signal store. Every future `get_price_comps` query for similar items is now grounded in real local sold data, not just web scraping.

**You own the demand signals.** Serper and eBay can be scraped by anyone. Your locally accumulated sold price history and buyer search behavior cannot be replicated by a competitor who starts later. That's the moat.

**The flywheel only works if `mark_sold` is called consistently.** Encourage sellers to use it.

---

## 4. File-by-File Reference

### Root Level

**`server.py`**
Entry point. Implements the MCP protocol and both transports.

Key components:
- `handle_jsonrpc()` — routes all JSON-RPC methods: `initialize`, `tools/list`, `tools/call`, `ping`, `notifications/*`
- `SSETransport` class — handles `/sse` (connection) and `/message` (JSON-RPC POST). Maintains a `_clients` dict of active SSE streams keyed by session ID. Sends 30-second heartbeats to keep connections alive.
- `run_stdio()` — reads newline-delimited JSON from stdin, writes responses to stdout.
- `create_app()` — assembles the aiohttp application. Registers SSE routes, billing routes, consumer HTTP routes, the landing page, and CORS middleware.
- Consumer routes (`/consumer/tools`, `/consumer/run`) — plain HTTP access for non-MCP clients and browser frontends. Allows calling tools without a full MCP client.

API key extraction from SSE requests: checks `X-API-Key` header first, then `Authorization: Bearer <token>`.

**`billing.py`**
Standalone billing module. Designed to be dropped into any MCP server. No database dependency — persists state to `/data/usage/billing_state.json` as JSON.

Key classes:
- `BillingConfig` — reads all billing config from environment variables at startup.
- `UsageTracker` — manages API keys, user usage, affiliates, rate limits. Loads/saves state to disk on every mutation.
- `APIKey` dataclass — key string, user ID, tier (`free`/`pro`), rate limit RPM, Stripe customer ID, affiliate code.
- `UserUsage` dataclass — per-user call counts, token totals, cost totals, calls by tool, billing period.
- `AffiliatePartner` dataclass — affiliate code, commission rate (default 20%), pending/paid commission tracking.

Key functions:
- `create_billing_middleware(tracker)` — returns an `async def middleware(tool_name, arguments, api_key_str, handler)` function. This is what `server.py` calls for every `tools/call`. When billing is disabled (`BILLING_ENABLED=false`), it passes through with an anonymous key.
- `add_billing_routes(app, tracker)` — registers all `/billing/*` and `/affiliate/*` HTTP routes on the aiohttp app.

**Rate limiting:** sliding 60-second window. Timestamps stored in memory (`_rate_windows` dict). Cleaned up on each check.

**Stripe metering:** fires asynchronously via `asyncio.create_task()` so it never blocks tool execution. Looks up the subscription item ID once per API key and caches it on the key object.

**`config.py`**
Singleton configuration loaded from environment variables. Call `get_config()` anywhere to get the `ServerConfig` object. Calls `load_dotenv()` on first access if `python-dotenv` is installed.

Current fields: `port` (8100), `host` (0.0.0.0), `auth_token` (optional bearer token), `transport` (sse/stdio/both). Domain-specific fields (database URL, Serper API key, etc.) should be added here when implementing `tools/resale.py`.

**`requirements.txt`**
Runtime dependencies: `aiohttp>=3.9` (async HTTP server and client), `python-dotenv>=1.0` (`.env` file loading), `stripe>=7.0` (Stripe SDK, optional at runtime — only imported if `STRIPE_SECRET_KEY` is set), `httpx>=0.27` (async HTTP client, used by Serper connector).

**`pyproject.toml`**
Python packaging metadata. Defines the `vintage-resale-mcp` CLI entry point (`vintage-resale-mcp = "server:main"`). Optional dependency groups: `reports` (Jinja2, WeasyPrint for PDF reports), `dev` (pytest, ruff). Ruff is configured at line-length 100.

**`docker-compose.yml`**
Two-service stack:
- `mcp-server` — builds from `Dockerfile`, binds `${SERVER_PORT:-8100}:8100`, mounts `mcp-data` volume at `/data/usage` for billing state persistence, runs Docker healthcheck against `/health`.
- `caddy` — Caddy 2 reverse proxy with automatic TLS. Only starts when you pass `--profile proxy`. Mounts `./Caddyfile`.

Three named volumes: `mcp-data` (billing state), `caddy-data` (TLS certificates), `caddy-config` (Caddy runtime config).

**`Dockerfile`**
`python:3.11-slim` base. Copies `requirements.txt` first (layer caching — dependency installs are cached unless requirements change). Copies application code. Creates `/data/usage`. Exposes 8100. Runs `python server.py` (SSE mode by default). Includes a Docker HEALTHCHECK.

**`Caddyfile`**
Reverse proxy configuration for production HTTPS. Replace `your-domain.com` with your actual domain. Caddy auto-provisions TLS via Let's Encrypt. The `@sse` block disables buffering and removes read timeout for the `/sse` endpoint — SSE connections are long-lived and must not be buffered or timed out by the proxy.

**`deploy.sh`**
Single operations script. All commands:

| Command | What it does |
|---|---|
| `./deploy.sh setup` | `cp .env.example .env`, `pip install -r requirements.txt`, `mkdir -p data/usage` |
| `./deploy.sh start` | `docker compose up -d --build` |
| `./deploy.sh stop` | `docker compose down` |
| `./deploy.sh restart` | `docker compose restart` |
| `./deploy.sh logs` | `docker compose logs -f --tail=100` |
| `./deploy.sh status` | Container status + `/health` endpoint |
| `./deploy.sh billing` | Hits `/billing/metrics` (requires `BILLING_ADMIN_KEY`) |
| `./deploy.sh create-key <user_id> [tier]` | Creates an API key via `/billing/keys` |
| `./deploy.sh benchmark` | Runs `strategy/competitor_analysis.py`, outputs to `reports/` and `site/` |
| `./deploy.sh fly` | Deploys to Fly.io (requires `fly` CLI) |
| `./deploy.sh railway` | Deploys to Railway (requires `railway` CLI) |

### tools/

**`tools/__init__.py`**
The tool registry. Imports `TOOLS` and `HANDLERS` from each tool module and aggregates them into `ALL_TOOLS` (list of tool definition dicts) and `ALL_HANDLERS` (dict of `tool_name -> async handler`). `server.py` imports only `ALL_TOOLS` and `ALL_HANDLERS` — it never imports tool modules directly. This is the single place to register new tool modules.

**`tools/example.py`**
Three template tools that ship with the base template. Serves as the canonical reference for how to write a tool.

- `echo` — returns input text unchanged. Tests basic connectivity.
- `hello_world` — greets by name with optional message. Tests parameterized calls.
- `get_status` — returns server uptime, platform, Python version, and registered tool count.

Each tool has a definition dict (JSON Schema) and an async handler function. The TOOLS list and HANDLERS dict at the bottom of the file are what `__init__.py` imports.

**`tools/resale.py`** — PLANNED. See section 5 for the full tool spec and section 11 for implementation status.

### middleware/ — PLANNED

This directory does not exist yet. See section 11.

**`middleware/signal_capture.py`** — Passive data collection. Fires non-blocking after every tool response. Records searches, price comp lookups, and sold events to `/data/signals/signals.json`. Powers `trending_now` and improves price intelligence over time.

**`middleware/serper_connector.py`** — Serper API integration for live Google Shopping / eBay / Etsy price data. 24-hour cache per query to avoid per-call API costs. Enriches `get_price_comps` responses.

**`middleware/session_manager.py`** — Tracks tool call history within a user session. Enables context-aware responses (e.g., if a user already searched for an item, the next call can skip the search and go straight to comps).

**`middleware/sync.py`** — Two-way sync engine. Pulls enriched context from the signal store before a tool executes. Pushes signals after. This is the mechanism that closes the flywheel loop.

### strategy/

**`strategy/competitor_analysis.py`**
Pricing benchmark and competitive positioning engine. Reads competitor profiles and a pricing policy, computes weighted scores, and outputs three files:
- `reports/competitive_report.md` — internal strategy brief with score gaps, pricing benchmarks, and improvement areas.
- `site/public-comparison.json` — safe public-facing comparison table (served at `/public-comparison.json`).
- `site/pricing-recommendation.json` — recommended price point with rationale.

Run with: `./deploy.sh benchmark` or directly:
```bash
python strategy/competitor_analysis.py \
  --competitors strategy/competitors.example.json \
  --policy strategy/pricing_policy.example.json \
  --output-root .
```

**`strategy/competitors.example.json`**
Example competitor profile format. Contains `our_product` (name, positioning, pricing, scores) and `competitors` array. Scores are numeric (0–10) across dimensions: `accuracy`, `workflow_depth`, `deployment_speed`, `consumer_usability`, `ops_visibility`. Copy and fill in real competitor data — do not commit proprietary intelligence to a public repo.

**`strategy/pricing_policy.example.json`**
Pricing policy constraints: score weights, premium/discount multipliers, price floor/ceiling, minimum free/pro call counts. The `competitor_analysis.py` engine uses these to compute a recommended price point.

### prompts/

System prompts for AI assistants deployed alongside this server. These are not used by the MCP server itself — they are prompts to give to a separate AI assistant that helps users install or evaluate the product.

**`prompts/install_assistant_system.md`** — Guides users through installation. Branches on technical vs. non-technical users. Technical path: create API key, set server URL, add `Authorization: Bearer <key>`, verify with a test call.

**`prompts/sales_qualification_system.md`** — Qualifies leads for Free/Pro/Enterprise tiers based on use case, expected volume, team size, and integration needs.

**`prompts/public_messaging_system.md`** — Public-facing assistant. Explains capabilities without disclosing internal algorithms, prompt chains, or model routing logic.

**`prompts/competitive_response_system.md`** — Produces competitive comparisons using data from `site/public-comparison.json` and `site/pricing-recommendation.json`. Never discloses internal heuristics.

### site/

**`site/index.html`**
Landing page and API key signup flow. Dark theme, Tailwind CSS via CDN, Inter + JetBrains Mono fonts. Served at `/` by `server.py`. This is where users discover the server and generate API keys. The page should POST to `/billing/keys` to create keys and link to `/billing/checkout` for paid upgrades.

**`site/public-comparison.json`** (generated)
Output of `strategy/competitor_analysis.py`. Served at `/public-comparison.json`. Contains public-safe competitor comparison data for the landing page.

---

## 5. The 8 Vintage Resale Tools

These are the tools defined in `tools/resale.py` (planned). The full specification is below so that whoever implements them builds to the right contract.

### 1. `search_inventory`

Main discovery tool. Buyers use this to find items.

```
Input:
  query       string  (required)  — keyword search, e.g. "1970s Levi's denim jacket"
  category    string  (optional)  — e.g. "clothing", "accessories", "furniture"
  min_price   number  (optional)  — minimum price in USD
  max_price   number  (optional)  — maximum price in USD
  condition   string  (optional)  — "excellent", "good", "fair", "parts"

Output: JSON array of matching items with id, title, price, condition, category, thumbnail_url

Signal captured: the search query + category + result count
```

### 2. `get_item`

Fetch full item details by ID.

```
Input:
  item_id     string  (required)  — item identifier

Output: full item object including description, measurements, photos, seller info, listing date

Signal captured: item access (demand indicator for popular items)
```

### 3. `get_price_comps`

Comparable sold prices plus a suggested price range. Always Serper-enriched with real eBay/Etsy comps. This is the tool sellers rely on most before pricing a new listing.

```
Input:
  description  string  (required)  — item description, e.g. "1970s Levi's 501 jeans 32x30 orange tab"
  category     string  (optional)
  condition    string  (optional)

Output:
  - local_sold: array of locally recorded sold prices for similar items
  - web_comps: array of eBay/Etsy listings from Serper (live, cached 24hr)
  - suggested_range: { low: number, high: number, recommended: number }
  - data_freshness: { local_updated: timestamp, web_updated: timestamp }

Signal captured: what item category is being researched for pricing
```

### 4. `trending_now`

What buyers are actually searching for, based on accumulated demand signals. Zero external API calls — reads only from the local signal store.

```
Input:
  category    string  (optional)  — filter by category
  limit       integer (optional)  — default 10

Output: ranked array of { term, category, search_count, trend_velocity }

Signal captured: none (read-only query of signal store)
```

### 5. `create_listing`

Add a new item to inventory.

```
Input:
  title        string  (required)
  description  string  (required)
  price        number  (required)  — asking price in USD
  category     string  (required)
  condition    string  (required)
  photos       array   (optional)  — array of image URLs
  seller_id    string  (required)

Output: { item_id: string, status: "active", listing_url: string }

Signal captured: new supply entered (category + price point)
```

### 6. `update_listing`

Modify an existing listing's price, description, or status.

```
Input:
  item_id      string  (required)
  price        number  (optional)
  description  string  (optional)
  status       string  (optional)  — "active", "paused", "sold"
  seller_id    string  (required)  — must match original seller

Output: updated item object

Signal captured: price changes (tracks price reduction patterns)
```

### 7. `mark_sold`

Mark an item as sold at the actual transaction price. **The most important signal for price intelligence.** Every recorded sold price makes future `get_price_comps` results more accurate for similar items.

```
Input:
  item_id       string  (required)
  sold_price    number  (required)  — actual transaction price in USD
  seller_id     string  (required)
  buyer_notes   string  (optional)  — condition notes, negotiation context

Output: { status: "sold", item_id, sold_price, recorded_at }

Signal captured: actual sold price + category + condition — highest-value signal in the system
```

### 8. `seller_stats`

Performance dashboard for a seller.

```
Input:
  seller_id    string  (required)
  period_days  integer (optional)  — default 30

Output:
  - total_listed: integer
  - total_sold: integer
  - sell_through_rate: float (0.0–1.0)
  - avg_days_to_sell: float
  - avg_sale_price: float
  - top_categories: array of { category, sold_count }
  - total_revenue_usd: float

Signal captured: none (read-only aggregation)
```

---

## 6. How to Add a New Tool

This is the exact pattern used in `tools/example.py`. Follow it precisely.

**Step 1: Define the tool in `tools/resale.py` (or a new module):**

```python
MY_NEW_TOOL = {
    "name": "my_tool_name",
    "description": "What this tool does. The AI reads this description to decide when to call the tool. Be specific about what it returns.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return. Default 10."
            }
        },
        "required": ["query"]
    },
    "annotations": {
        "readOnlyHint": True,      # True if this tool never writes data
        "destructiveHint": False,  # True if this tool deletes or irreversibly modifies data
        "idempotentHint": True,    # True if calling twice with same args produces same result
        "openWorldHint": False,    # True if this tool queries external sources (Serper, eBay, etc.)
    }
}
```

**Step 2: Write the handler:**

```python
async def handle_my_tool(query: str, limit: int = 10, **kwargs) -> str:
    # **kwargs absorbs any extra args billing middleware may pass
    results = do_the_work(query, limit)
    return json.dumps({"results": results, "count": len(results)})
```

Handler rules:
- Must be `async def`
- Must return a `str` (JSON-encoded is conventional)
- Parameter names must match the keys in `inputSchema.properties`
- Include `**kwargs` to absorb unexpected arguments gracefully
- Raise exceptions freely — the billing middleware catches them and records the error

**Step 3: Register in the module's export lists:**

```python
# At the bottom of tools/resale.py:
TOOLS = [
    SEARCH_INVENTORY_TOOL,
    GET_ITEM_TOOL,
    # ...existing tools...
    MY_NEW_TOOL,      # add here
]

HANDLERS = {
    "search_inventory": handle_search_inventory,
    # ...existing handlers...
    "my_tool_name": handle_my_tool,   # add here
}
```

**Step 4: Register the module in `tools/__init__.py`:**

```python
from tools.resale import TOOLS as RESALE_TOOLS, HANDLERS as RESALE_HANDLERS

ALL_TOOLS: List[Dict[str, Any]] = [
    *EXAMPLE_TOOLS,
    *RESALE_TOOLS,   # add this line
]

ALL_HANDLERS: Dict[str, Callable[..., Coroutine]] = {
    **EXAMPLE_HANDLERS,
    **RESALE_HANDLERS,   # add this line
}
```

**Step 5: Add the tool price to `billing.py`:**

```python
# In BillingConfig.__init__():
self.tool_prices = {
    "echo": 0.0005,
    "my_tool_name": 0.002,   # add your tool's per-call price in USD
}
```

Tools not in `tool_prices` default to `$0.001` per call.

**Step 6: Restart and verify:**

```bash
./deploy.sh restart
curl http://localhost:8100/health
# tools count should have increased

curl http://localhost:8100/consumer/tools
# your new tool should appear in the list
```

---

## 7. Configuration Reference

All configuration is via environment variables. Copy `.env.example` to `.env` and fill in values before starting.

### Core Server

| Variable | Default | Required | Description |
|---|---|---|---|
| `SERVER_PORT` | `8100` | No | HTTP port for SSE transport |
| `SERVER_HOST` | `0.0.0.0` | No | Bind address. Use `127.0.0.1` for local-only. |
| `SERVER_AUTH_TOKEN` | `` | No | Bearer token for stdio auth. Not checked for SSE (billing keys handle that). |
| `SERVER_TRANSPORT` | `sse` | No | `sse`, `stdio`, or `both` |

### Billing

| Variable | Default | Required | Description |
|---|---|---|---|
| `BILLING_ENABLED` | `false` | No | Set `true` to enforce API key auth and rate limits. While `false`, all requests are anonymous and unlimited. |
| `BILLING_ADMIN_KEY` | `` | No | Admin key for `/billing/metrics`. If empty, the endpoint is open. |
| `FREE_TIER_CALLS` | `100` | No | Monthly call limit for free-tier API keys |
| `RATE_LIMIT_RPM` | `60` | No | Requests per minute limit per API key |
| `USAGE_LOG_DIR` | `/data/usage` | No | Directory for `billing_state.json`. The Docker volume mounts here. |

### Stripe (optional — only needed for paid subscriptions)

| Variable | Default | Required | Description |
|---|---|---|---|
| `STRIPE_SECRET_KEY` | `` | No | Stripe secret key (`sk_live_...`). If empty, Stripe metering is disabled. |
| `STRIPE_PRICE_ID` | `` | No | Stripe price ID for usage-based billing |
| `STRIPE_WEBHOOK_SECRET` | `` | No | Webhook signing secret for `/billing/webhook` |

### Affiliate Program

| Variable | Default | Required | Description |
|---|---|---|---|
| `AFFILIATE_ENABLED` | `true` | No | Enable/disable affiliate program |
| `AFFILIATE_DEFAULT_RATE` | `0.20` | No | Default commission rate (20%). Must be between 0.01 and 0.50. |
| `AFFILIATE_PAYOUT_THRESHOLD` | `100.00` | No | Minimum pending commission (USD) before payout is offered |

### Domain-Specific (add to `config.py` when implementing resale tools)

| Variable | Default | Required | Description |
|---|---|---|---|
| `SERPER_API_KEY` | `` | Yes (for price comps) | Serper.dev API key for Google Shopping enrichment |
| `SERPER_CACHE_TTL` | `86400` | No | Serper response cache TTL in seconds (default: 24 hours) |
| `INVENTORY_DATA_DIR` | `/data/inventory` | No | Path to inventory JSON store |
| `SIGNALS_DATA_DIR` | `/data/signals` | No | Path to demand signal store |

---

## 8. Deployment Guide

### Local Development (no Docker)

```bash
# 1. Clone and enter the project
cd vintage-resale-mcp

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and edit config
cp .env.example .env
# Edit .env: set BILLING_ENABLED=false for dev

# 5. Start the server
python server.py

# 6. Verify
curl http://localhost:8100/health
```

### Local Development (Docker)

```bash
./deploy.sh setup   # creates .env, installs deps, creates data dir
./deploy.sh start   # docker compose up -d --build
./deploy.sh logs    # tail output
./deploy.sh status  # containers + health check
```

### Production with HTTPS (Docker + Caddy)

1. Point your domain's DNS A record to your server IP.
2. Edit `Caddyfile` — replace `your-domain.com` with your actual domain.
3. Start with the proxy profile:

```bash
docker compose --profile proxy up -d
```

Caddy automatically provisions TLS via Let's Encrypt. The `/sse` endpoint has buffering disabled and no read timeout — required for SSE connections to work through a proxy.

### Railway (fastest)

```bash
# Install Railway CLI: https://docs.railway.app/develop/cli
./deploy.sh railway
```

Or use the Railway dashboard to import the GitHub repo directly. Set environment variables in the Railway project settings.

### Fly.io

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
./deploy.sh fly
```

First run creates `fly.toml` via `fly launch --no-deploy`, imports secrets from `.env`, then deploys.

### Creating API Keys in Production

```bash
# Via deploy.sh:
./deploy.sh create-key user@example.com pro

# Via curl:
curl -X POST http://localhost:8100/billing/keys \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user@example.com", "tier": "pro"}'

# Response:
# { "api_key": "mcp_...", "user_id": "...", "tier": "pro" }
```

### Competitive Pricing Analysis

```bash
# Run the benchmark engine:
./deploy.sh benchmark

# Or with custom data files:
python strategy/competitor_analysis.py \
  --competitors strategy/competitors.example.json \
  --policy strategy/pricing_policy.example.json \
  --output-root .

# Outputs:
# reports/competitive_report.md       -- internal strategy brief
# site/public-comparison.json         -- served at /public-comparison.json
# site/pricing-recommendation.json    -- recommended price point
```

To customize: copy `competitors.example.json` to `competitors.json`, fill in real competitor data and your actual scores, then run with `--competitors competitors.json`.

---

## 9. Registering in Claude Desktop

### Option A: stdio (local, no server required)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "vintage-resale": {
      "command": "python",
      "args": ["/absolute/path/to/vintage-resale-mcp/server.py", "--stdio"],
      "env": {
        "BILLING_ENABLED": "false"
      }
    }
  }
}
```

The server process is launched by Claude Desktop. stdio mode uses stdin/stdout — no HTTP port required.

### Option B: SSE (remote server)

```json
{
  "mcpServers": {
    "vintage-resale": {
      "url": "https://your-domain.com/sse",
      "headers": {
        "X-API-Key": "mcp_your_api_key_here"
      }
    }
  }
}
```

Replace `your-domain.com` and `mcp_your_api_key_here` with your values.

### Verifying the connection

After adding the config and restarting Claude Desktop, open a new conversation and ask: "What tools do you have available?" You should see the vintage resale tools listed. Or call `get_status` directly to confirm the server is live.

---

## 10. HTTP API Reference

Beyond the MCP protocol, the server exposes these HTTP endpoints.

### MCP Protocol

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/sse` | Establish SSE connection. Returns `event: endpoint` with session ID. |
| `POST` | `/message?sessionId=<id>` | Send JSON-RPC message. Response also pushed to SSE stream. |
| `POST` | `/messages?sessionId=<id>` | Alias for `/message`. |

### Health

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Returns `{status, server, version, protocol, tools, connected_clients}` |

### Consumer (non-MCP HTTP access)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/consumer/tools` | JSON list of all registered tools (name, description, inputSchema) |
| `POST` | `/consumer/run` | Run a tool via plain HTTP. Body: `{tool, arguments, api_key}`. Returns `{ok, tool, result}`. |
| `GET` | `/` | Landing page (`site/index.html`) |
| `GET` | `/public-comparison.json` | Competitor comparison data (generated by benchmark) |

### Billing

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/billing/keys` | None | Create API key. Body: `{user_id, name?, tier?, affiliate_code?}` |
| `GET` | `/billing/usage?api_key=<key>` | API key | Usage summary for the key's user |
| `GET` | `/billing/activity?api_key=<key>&limit=50` | API key | Recent call history |
| `GET` | `/billing/metrics?admin_key=<key>` | Admin key | Global metrics (all users, revenue, tool call counts) |
| `POST` | `/billing/checkout` | None | Create Stripe checkout session. Body: `{user_id, tier?, success_url?, cancel_url?}` |
| `POST` | `/billing/webhook` | Stripe signature | Stripe webhook handler (handles `checkout.session.completed`, `customer.subscription.deleted`) |

### Affiliates

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/affiliate/signup` | None | Register affiliate partner. Body: `{partner_name, payout_email, commission_rate?}` |
| `GET` | `/affiliate/dashboard?code=<code>` | None | Affiliate stats (referred calls, revenue, pending commission) |
| `POST` | `/affiliate/attach` | None | Attach affiliate code to existing user. Body: `{user_id, affiliate_code}` |
| `GET` | `/affiliate/public-offer` | None | Public affiliate program terms (enabled, rate, payout threshold) |

---

## 11. Current State vs. Planned Features

The codebase is a working MCP server (protocol, billing, transports all live) with placeholder domain tools. The vintage resale logic is the next implementation layer.

### What is live and working today

- Full MCP protocol implementation (SSE + stdio)
- Billing: API keys, rate limiting, free tier, Stripe metering, affiliate commissions
- Consumer HTTP routes (`/consumer/tools`, `/consumer/run`)
- Three template tools: `echo`, `hello_world`, `get_status`
- Tool registry pattern (`tools/__init__.py`)
- Landing page (`site/index.html`)
- Competitor pricing analysis engine (`strategy/competitor_analysis.py`)
- Docker + Caddy deployment stack
- Fly.io and Railway deploy scripts

### What needs to be built

| Component | File | Priority | Notes |
|---|---|---|---|
| Vintage resale tools | `tools/resale.py` | High | All 8 tools spec'd in section 5 |
| Signal capture middleware | `middleware/signal_capture.py` | High | The flywheel depends on this |
| Serper enrichment | `middleware/serper_connector.py` | High | Required for `get_price_comps` web comps |
| Sync engine | `middleware/sync.py` | Medium | Context pull/push around tool calls |
| Session manager | `middleware/session_manager.py` | Medium | Cross-call context awareness |
| Inventory data store | `/data/inventory/` | High | JSON file store or SQLite |
| Signal data store | `/data/signals/signals.json` | High | Written by signal capture |
| `.env.example` | `.env.example` | Medium | Template for operators |

### How billing.py tool prices need updating

When `tools/resale.py` is implemented, add pricing to `BillingConfig.tool_prices` in `billing.py`:

```python
self.tool_prices = {
    "echo": 0.0005,
    "hello_world": 0.0005,
    "get_status": 0.0,
    # Resale tools:
    "search_inventory": 0.002,
    "get_item": 0.001,
    "get_price_comps": 0.005,   # higher: Serper enrichment has a cost
    "trending_now": 0.001,
    "create_listing": 0.002,
    "update_listing": 0.001,
    "mark_sold": 0.001,
    "seller_stats": 0.002,
}
```

---

## 12. For AI Agents

This section is written specifically for AI agents (Claude, ChatGPT, or others) using these tools. If you are a human, this section explains how to design AI behavior on top of this server.

### Your role

You are an assistant helping two types of users:

- **Buyers** — looking for specific vintage items, comparing prices, making purchase decisions.
- **Sellers** — pricing new items, managing their inventory, understanding what's trending.

You are not a replacement for the marketplace UI. You are an intelligent layer on top of it that can answer questions, make recommendations, and take actions on behalf of users.

### Recommended tool call sequences

**For a buyer looking for an item:**
1. `trending_now` — understand current demand before making recommendations. If the buyer's target category is trending, mention it.
2. `search_inventory` — find matching items.
3. `get_item` — fetch full details for items of interest.
4. `get_price_comps` — if the buyer asks whether a price is fair, run comps on the specific item.

**For a seller pricing a new item:**
1. `get_price_comps` — always call this before suggesting a price. Never suggest a price from general knowledge alone.
2. `trending_now` — check if the item's category is trending. Trending items can often be priced at the higher end of the comp range.
3. `create_listing` — once the seller agrees on a price, create the listing.

**For a seller reviewing their performance:**
1. `seller_stats` — pull their dashboard first.
2. `trending_now` — compare their active categories to what's trending. Identify gaps.

### Critical behaviors

**Always call `get_price_comps` before suggesting a price.** Do not suggest a price from training data. Vintage item prices are highly condition- and era-specific. The comps tool returns real sold data and live web comps — use them.

**Always encourage `mark_sold`.** Every time a seller mentions a sale, prompt them to call `mark_sold` with the actual transaction price. This is the most valuable signal in the system. A seller who consistently marks sold items helps every future buyer and seller who searches similar items.

**Be honest about data freshness.** The `get_price_comps` response includes `data_freshness` timestamps. If local sold data is sparse or old, say so. Web comps from Serper are live (cached up to 24 hours). Local sold data grows over time — it may be thin early in the platform's lifecycle.

**Do not over-call.** Signal capture fires on every tool call. Redundant calls waste billing quota and pollute the signal store with noise. Call `search_inventory` once with good parameters rather than in a loop.

**`trending_now` is zero-cost externally.** It reads only from the local signal store — no Serper call, no external latency. Call it freely at the start of sessions.

### What you do not need to think about

- **Signal capture** — it fires automatically, non-blocking, after every tool response. You do not need to make any extra calls to record signals.
- **Serper enrichment** — it happens automatically inside `get_price_comps`. You do not call Serper directly.
- **Billing** — the billing middleware handles auth and metering before your tool call reaches the handler. If a user's key is invalid or over limit, you will receive an error response, not a tool result.
- **Session tracking** — the session manager records your call history automatically. Future calls in the same session may receive richer context because of earlier calls.

### Error handling

If a tool returns an error, read the `error.message` field:

- `"Invalid API key"` — the user's API key is missing or revoked. Direct them to the landing page to get a key.
- `"Rate limit exceeded"` — too many calls per minute. Wait 60 seconds and retry.
- `"Free tier limit exceeded"` — the user has used their 100 free calls this month. Direct them to `/billing/checkout` to upgrade.
- `"Unknown tool: ..."` — the tool name is incorrect. Call `get_status` to see registered tools.

### Example: helping a buyer find and evaluate a vintage jacket

```
User: "I'm looking for a 1960s Levi's denim jacket. Is now a good time to buy?"

Agent workflow:
1. trending_now(category="clothing")
   → See if 1960s denim is trending up or down
2. search_inventory(query="1960s Levi's denim jacket", category="clothing")
   → Find available items
3. get_price_comps(description="1960s Levi's denim jacket", category="clothing")
   → Get a fair price range to evaluate listings
4. Synthesize: "Levi's denim from this era is [trending/stable/cooling].
   I found [N] items. Prices on similar items run $X–$Y based on recent sales.
   The listing at $Z is [fair/above/below] market."
```

---

*Last updated: 2026-03-09*
*Protocol: MCP 2024-11-05*
*Server version: 0.1.0 (see `pyproject.toml`)*
