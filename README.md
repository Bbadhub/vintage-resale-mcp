# Vintage Resale MCP

MCP server for vintage resale — inventory search, pricing comps, listing management, and passive market signal collection.

---

## Start Here — Run the Onboarding Session

Before touching any code, run the interactive onboarding. It will teach you how this system works, why it was built this way, and help you figure out exactly what to change for your use case.

**You need:** [Claude Code CLI](https://claude.ai/claude-code) installed, or any Claude chat session.

### Option A — Claude Code CLI (recommended)

```bash
# Clone the repo
git clone https://github.com/Bbadhub/vintage-resale-mcp.git
cd vintage-resale-mcp

# Run the onboarding session
claude --print "$(cat ONBOARDING_SESSION.md)"
```

Or launch an interactive session with the prompt pre-loaded:

```bash
claude -p "$(sed -n '/^---$/,$ p' ONBOARDING_SESSION.md | tail -n +3)"
```

### Option B — Claude.ai Chat

1. Open [claude.ai](https://claude.ai)
2. Open `ONBOARDING_SESSION.md` in any text editor
3. Copy everything **below** the second `---` divider (the system prompt)
4. Paste it into a new Claude conversation
5. Claude will start asking you questions — answer honestly, it adapts to your use case

### Option C — Cursor / VS Code

Open this repo in Cursor or VS Code with a Claude extension, then in the AI chat:

```
Please read ONBOARDING_SESSION.md and run the onboarding session with me, starting from Question 1.
```

---

## What the Onboarding Covers

The session walks you through 6 questions. After each answer, you get:

- **Chain of Thought** — why the code is built the way it is, not just what it does
- **Scenarios** — concrete examples of data flowing through the system
- **Your action plan** — by the end, you know exactly what files to change for your domain

Topics covered:
1. Your problem and how MCP tools solve it (`server.py`, `tools/`)
2. What user data is worth collecting (`middleware/signal_capture.py`)
3. How to charge for the service (`billing.py`)
4. When web enrichment makes tools significantly better (`middleware/serper_connector.py`)
5. How to scale signals across multiple servers (`middleware/sync.py`)
6. Mapping YOUR domain tools to this template structure

Full reference doc (non-interactive): [ONBOARDING.md](ONBOARDING.md)

---

## Project Structure

```
vintage-resale-mcp/
├── server.py                  # MCP protocol server (SSE + stdio)
├── billing.py                 # API keys, Stripe, rate limits, affiliates
├── config.py                  # All env vars loaded in one place
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container build
├── docker-compose.yml         # Local + production stack
├── deploy.sh                  # One-script ops: setup, start, logs, deploy
├── .env.example               # Every config var with explanations
│
├── tools/
│   ├── __init__.py            # Aggregates ALL_TOOLS + ALL_HANDLERS
│   ├── resale.py              # The 8 vintage resale domain tools
│   └── example.py            # Template reference tools (echo, hello_world)
│
├── middleware/
│   ├── signal_capture.py      # Passive data collection on every tool call
│   ├── serper_connector.py    # Google SERP enrichment, cached 24hr
│   ├── session_manager.py     # Session state across tool calls
│   └── sync.py               # Two-way sync engine (the data flywheel)
│
├── site/
│   └── index.html             # Landing page + API signup flow
│
├── strategy/
│   ├── competitor_analysis.py # Pricing benchmark generator
│   └── *.example.json         # Competitor + pricing policy templates
│
├── prompts/
│   └── *.md                   # AI system prompts for sales/install/support
│
├── ONBOARDING.md              # Full reference doc (engineer + AI agent)
└── ONBOARDING_SESSION.md      # Interactive onboarding prompt (start here)
```

---

## Quick Start (after onboarding)

```bash
# 1. Configure
cp .env.example .env
# Edit .env — minimum required: nothing (runs in dev mode with billing disabled)

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start
./deploy.sh setup
./deploy.sh start

# 4. Verify
curl http://localhost:8100/health
curl http://localhost:8100/consumer/tools
```

---

## The 8 Tools

| Tool | What it does | Signal captured |
|------|-------------|----------------|
| `search_inventory` | Search items by keyword, category, price, condition | Search term (demand signal) |
| `get_item` | Full item details by ID | Item view |
| `get_price_comps` | Comparable sold prices + suggested range (Serper-enriched) | Price research intent |
| `trending_now` | Top searches from real signal data | Reads signals, writes none |
| `create_listing` | Add a new item to inventory | New supply signal |
| `update_listing` | Edit price, description, status | Inventory change |
| `mark_sold` | Mark item sold at actual price | **Most valuable signal** |
| `seller_stats` | Performance dashboard for a seller | Reads signals |

`mark_sold` is free to call by design — every actual sold price that enters the system improves future price comps for everyone.

---

## Key Config (`.env`)

```bash
# Minimum to run (dev mode)
SERVER_PORT=8100

# Turn on billing when ready
BILLING_ENABLED=true
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PRICE_ID=price_...
FREE_TIER_CALLS=100

# Add Serper for web-enriched price comps
SERPER_API_KEY=your-serper-key
SERPER_TOOLS=get_price_comps,search_inventory

# Add sync endpoint to share signals across servers
SYNC_ENDPOINT=https://your-central-store.com
```

Full config reference: [ONBOARDING.md — Configuration Reference](ONBOARDING.md#7-configuration-reference)

---

## Extend with Your Own Tools

```python
# In tools/resale.py — add a new tool definition
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
./deploy.sh start      # Local Docker Compose
./deploy.sh fly        # Fly.io
./deploy.sh railway    # Railway (fastest setup)
./deploy.sh benchmark  # Run competitive pricing analysis
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
