# Vintage Resale MCP

A production-ready MCP server that gives any AI model (Claude, ChatGPT, etc.) tools for a vintage resale marketplace — inventory search, price comps, listings, and passive market signal collection. Built on [mcp-saas-template](https://github.com/Bbadhub/mcp-saas-template) with billing, Stripe, and a data flywheel baked in.

---

## Getting Started — Paste This Into Your Claude Code CLI

Open your terminal and paste this single prompt into Claude Code. It will clone the repo, read the codebase, and walk you through an interactive onboarding session — teaching you what everything does, why it was built that way, and how to adapt it for your use case.

```
Clone the repo at https://github.com/Bbadhub/vintage-resale-mcp into a local folder, then read ONBOARDING_SESSION.md and run the interactive onboarding session with me starting from Question 1. Do not skip ahead — ask one question at a time and wait for my answer before continuing.
```

That's it. Claude Code will handle the clone and guide you through the rest.

---

## What This Is

An MCP server is a tool server for AI models. Instead of a human clicking a button, an AI model calls your tools directly — search inventory, check prices, create listings — and speaks the results back to the user in natural language.

This repo gives you:

- **8 domain tools** — search, get item, price comps, trending, create/update/mark sold, seller stats
- **Data flywheel** — every tool call passively captures signals (search terms, sold prices) that make future results smarter
- **Serper enrichment** — price comp tools are silently enriched with live eBay/Etsy data via Google SERP
- **Billing** — API keys, free tier, Stripe metering, affiliate commissions, rate limiting
- **Deploy stack** — Docker Compose, Fly.io, Railway, one-command ops script
- **Interactive onboarding** — guided session that teaches the codebase and helps you find your own use case

---

## Project Structure

```
vintage-resale-mcp/
├── server.py                  # MCP protocol (SSE + stdio), middleware chain
├── billing.py                 # API keys, Stripe, rate limits, affiliates
├── config.py                  # All env vars in one place
├── tools/
│   ├── resale.py              # The 8 domain tools
│   └── example.py            # Template reference (echo, hello_world)
├── middleware/
│   ├── signal_capture.py      # Passive data collection on every call
│   ├── serper_connector.py    # Google SERP enrichment, cached 24hr
│   ├── session_manager.py     # Session state across tool calls
│   └── sync.py               # Two-way sync engine
├── site/index.html            # Landing page + API signup
├── strategy/                  # Competitive pricing analysis tools
├── prompts/                   # AI system prompts for sales/support
├── ONBOARDING.md              # Full reference doc
└── ONBOARDING_SESSION.md      # Interactive onboarding (the prompt above runs this)
```

---

## Quick Setup (after onboarding)

```bash
cp .env.example .env          # copy config template
pip install -r requirements.txt
./deploy.sh setup
./deploy.sh start

curl http://localhost:8100/health         # verify running
curl http://localhost:8100/consumer/tools # list all tools
```

---

## The 8 Tools

| Tool | What it does | Signal captured |
|------|-------------|----------------|
| `search_inventory` | Search by keyword, category, price, condition | Search term (demand signal) |
| `get_item` | Full item details by ID | Item view |
| `get_price_comps` | Comparable sold prices + suggested range (Serper-enriched) | Price research intent |
| `trending_now` | Top searches from real signal data | Reads signals, writes none |
| `create_listing` | Add a new item | New supply signal |
| `update_listing` | Edit price, description, status | Inventory change |
| `mark_sold` | Mark item sold at actual price | Most valuable signal |
| `seller_stats` | Performance dashboard for a seller | Reads signals |

`mark_sold` is free to call by design. Every actual sold price that enters the system makes future price comps better for everyone.

---

## Key Config (`.env`)

```bash
SERVER_PORT=8100

# Billing (off by default for dev)
BILLING_ENABLED=true
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PRICE_ID=price_...
FREE_TIER_CALLS=100

# Web enrichment for price comps
SERPER_API_KEY=your-serper-key
SERPER_TOOLS=get_price_comps,search_inventory

# Share signals across servers
SYNC_ENDPOINT=https://your-central-store.com
```

Full config reference in [ONBOARDING.md](ONBOARDING.md#7-configuration-reference).

---

## Add Your Own Tools

```python
# tools/resale.py — add a definition
MY_TOOL = {
    "name": "my_tool",
    "description": "What the AI sees when deciding whether to call this",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"}
        },
        "required": ["query"]
    },
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
}

async def handle_my_tool(query: str, **kwargs) -> str:
    return json.dumps({"result": f"You searched for: {query}"})

# Register at bottom of file
TOOLS = [..., MY_TOOL]
HANDLERS = {..., "my_tool": handle_my_tool}
```

---

## Deploy

```bash
./deploy.sh start      # Docker Compose (local or VPS)
./deploy.sh fly        # Fly.io
./deploy.sh railway    # Railway (fastest)
./deploy.sh benchmark  # Competitive pricing analysis
./deploy.sh logs       # Tail logs
```

---

## Connect to Claude Desktop

**Remote (SSE):**
```json
{
  "mcpServers": {
    "vintage-resale": {
      "url": "https://your-domain.com/sse",
      "headers": { "X-API-Key": "your-api-key" }
    }
  }
}
```

**Local (stdio):**
```json
{
  "mcpServers": {
    "vintage-resale": {
      "command": "python",
      "args": ["path/to/server.py", "--stdio"]
    }
  }
}
```
