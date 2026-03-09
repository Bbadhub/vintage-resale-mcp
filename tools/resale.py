"""
Vintage Resale MCP Tools

8 production tools covering the full resale lifecycle:
  search_inventory, get_item, get_price_comps, trending_now,
  create_listing, update_listing, mark_sold, seller_stats

Storage: /data/inventory/items.json (JSON array, created on first write).
Mock data is returned when the store is empty so the server works out of box.
Serper enrichment is applied to search_inventory and get_price_comps.
Signal capture fires for every search and every write event.
"""

import json
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

import os
_INVENTORY_PATH = os.environ.get("INVENTORY_PATH", "/data/inventory/items.json")
_SIGNALS_PATH   = os.environ.get("SIGNALS_PATH",   "/data/signals/signals.json")

_CATEGORIES = ["clothing", "shoes", "accessories", "furniture",
               "collectibles", "electronics", "books", "other"]
_CONDITIONS = ["excellent", "good", "fair", "poor"]


# ---------------------------------------------------------------------------
# Inventory store helpers
# ---------------------------------------------------------------------------

def _load_inventory() -> List[Dict[str, Any]]:
    """Load all items from the JSON store.  Returns [] on any error."""
    path = Path(_INVENTORY_PATH)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        logger.debug("resale: inventory load failed", exc_info=True)
        return []


def _save_inventory(items: List[Dict[str, Any]]) -> None:
    """Persist items list to the JSON store, creating the file if needed."""
    path = Path(_INVENTORY_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(items, fh, indent=2, default=str)
    except Exception:
        logger.warning("resale: inventory save failed", exc_info=True)


def _mock_items() -> List[Dict[str, Any]]:
    """Return realistic sample items so the server works before any listings exist."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "id": "item_001",
            "title": "Levi's 501 Jeans — 32x30 — 1990s",
            "description": "Classic 90s deadstock Levi's 501s, light wash, button fly. No fading, original tag attached.",
            "price": 95.00,
            "condition": "excellent",
            "category": "clothing",
            "seller_id": "seller_abc",
            "listed_at": now,
            "status": "active",
            "thumbnail_url": "https://example.com/img/item_001.jpg",
            "photos": ["https://example.com/img/item_001.jpg"],
            "measurements": {"waist": "32", "inseam": "30", "rise": "10.5"},
            "provenance": "Purchased at estate sale, Phoenix AZ 1994",
        },
        {
            "id": "item_002",
            "title": "Nike Air Max 95 OG — Size 10 — Neon",
            "description": "Original colourway, worn twice, box included. Minor creasing on toe box.",
            "price": 285.00,
            "condition": "good",
            "category": "shoes",
            "seller_id": "seller_xyz",
            "listed_at": now,
            "status": "active",
            "thumbnail_url": "https://example.com/img/item_002.jpg",
            "photos": ["https://example.com/img/item_002.jpg"],
            "measurements": {"size_us": "10", "size_eu": "44"},
            "provenance": "Personal collection",
        },
        {
            "id": "item_003",
            "title": "Bakelite Rotary Telephone — 1950s Black",
            "description": "Fully functional Western Electric 500 desk phone. Dial works, bell rings, cord intact.",
            "price": 145.00,
            "condition": "good",
            "category": "collectibles",
            "seller_id": "seller_abc",
            "listed_at": now,
            "status": "active",
            "thumbnail_url": "https://example.com/img/item_003.jpg",
            "photos": ["https://example.com/img/item_003.jpg"],
            "measurements": {},
            "provenance": "Found in grandmother's attic, original handset cord",
        },
        {
            "id": "item_004",
            "title": "Pendleton Wool Blanket — Chief Joseph Pattern",
            "description": "100% virgin wool, dry cleaned, vibrant colours. Small moth hole on corner (1cm).",
            "price": 180.00,
            "condition": "fair",
            "category": "other",
            "seller_id": "seller_def",
            "listed_at": now,
            "status": "active",
            "thumbnail_url": "https://example.com/img/item_004.jpg",
            "photos": ["https://example.com/img/item_004.jpg"],
            "measurements": {"size": "64x80 inches"},
            "provenance": "Western Oregon estate",
        },
        {
            "id": "item_005",
            "title": "Vintage Rolex Datejust 1601 — 36mm — 1972",
            "description": "Silver dial, original jubilee bracelet, keeps excellent time, service history available.",
            "price": 4200.00,
            "condition": "excellent",
            "category": "accessories",
            "seller_id": "seller_xyz",
            "listed_at": now,
            "status": "active",
            "thumbnail_url": "https://example.com/img/item_005.jpg",
            "photos": ["https://example.com/img/item_005.jpg"],
            "measurements": {"diameter_mm": "36"},
            "provenance": "Family heirloom, original papers and box",
        },
    ]


def _get_items_or_mock() -> List[Dict[str, Any]]:
    """Return live inventory or seed with mocks if empty."""
    items = _load_inventory()
    return items if items else _mock_items()


def _find_item(items: List[Dict[str, Any]], item_id: str) -> Optional[Dict[str, Any]]:
    return next((i for i in items if i.get("id") == item_id), None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mcp_result(text: str) -> Dict[str, Any]:
    """Wrap a string result in MCP content format."""
    return {"content": [{"type": "text", "text": text}]}


def _mcp_json(obj: Any) -> Dict[str, Any]:
    """Wrap a JSON-serialisable object in MCP content format."""
    return _mcp_result(json.dumps(obj, indent=2, default=str))


# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------

SEARCH_INVENTORY_TOOL = {
    "name": "search_inventory",
    "description": (
        "Search the vintage resale inventory by keyword, category, price range, "
        "and condition. Returns matching items with market context from the web."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword search (title, description, provenance).",
            },
            "category": {
                "type": "string",
                "enum": _CATEGORIES,
                "description": "Filter by item category.",
            },
            "min_price": {
                "type": "number",
                "description": "Minimum price (USD).",
            },
            "max_price": {
                "type": "number",
                "description": "Maximum price (USD).",
            },
            "condition": {
                "type": "string",
                "enum": _CONDITIONS,
                "description": "Minimum condition filter.",
            },
        },
        "required": [],
    },
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}

GET_ITEM_TOOL = {
    "name": "get_item",
    "description": (
        "Get full details of a single inventory item including description, "
        "photos, measurements, provenance, and seller info."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
                "description": "The unique item ID.",
            },
        },
        "required": ["item_id"],
    },
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}

GET_PRICE_COMPS_TOOL = {
    "name": "get_price_comps",
    "description": (
        "Get comparable sold prices for a vintage item. "
        "Returns recent sold comparables, a suggested price range, and market trend. "
        "Uses live web data from Serper to fetch real market comps."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Item title or search phrase (e.g. 'Levi 501 jeans 32x30').",
            },
            "category": {
                "type": "string",
                "enum": _CATEGORIES,
                "description": "Item category.",
            },
            "condition": {
                "type": "string",
                "enum": _CONDITIONS,
                "description": "Item condition (optional, improves accuracy).",
            },
        },
        "required": ["title", "category"],
    },
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
}

TRENDING_NOW_TOOL = {
    "name": "trending_now",
    "description": (
        "See what vintage items and categories are trending based on search activity "
        "on this platform. Powered by local signal data — no external calls needed."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of trending items to return (default 10).",
                "default": 10,
                "minimum": 1,
                "maximum": 50,
            },
        },
        "required": [],
    },
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}

CREATE_LISTING_TOOL = {
    "name": "create_listing",
    "description": "Create a new vintage item listing in the marketplace.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Item title.",
            },
            "description": {
                "type": "string",
                "description": "Detailed item description including any flaws.",
            },
            "price": {
                "type": "number",
                "description": "Asking price in USD.",
            },
            "category": {
                "type": "string",
                "enum": _CATEGORIES,
                "description": "Item category.",
            },
            "condition": {
                "type": "string",
                "enum": _CONDITIONS,
                "description": "Item condition.",
            },
            "photos": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of photo URLs (optional).",
            },
        },
        "required": ["title", "description", "price", "category", "condition"],
    },
    "annotations": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
}

UPDATE_LISTING_TOOL = {
    "name": "update_listing",
    "description": "Update an existing listing (price, description, condition, or status).",
    "inputSchema": {
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
                "description": "The unique item ID to update.",
            },
            "price": {
                "type": "number",
                "description": "New price in USD (optional).",
            },
            "description": {
                "type": "string",
                "description": "Updated description (optional).",
            },
            "condition": {
                "type": "string",
                "enum": _CONDITIONS,
                "description": "Updated condition (optional).",
            },
            "status": {
                "type": "string",
                "enum": ["active", "sold", "reserved", "removed"],
                "description": "Listing status (optional).",
            },
        },
        "required": ["item_id"],
    },
    "annotations": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
}

MARK_SOLD_TOOL = {
    "name": "mark_sold",
    "description": (
        "Mark an item as sold and record the actual sale price. "
        "CRITICAL for the data flywheel — captures real price signals that "
        "improve future price recommendations for everyone."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
                "description": "The item ID to mark as sold.",
            },
            "sold_price": {
                "type": "number",
                "description": "Actual sale price in USD.",
            },
            "buyer_note": {
                "type": "string",
                "description": "Optional note about the buyer or sale (not public).",
            },
        },
        "required": ["item_id", "sold_price"],
    },
    "annotations": {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
}

SELLER_STATS_TOOL = {
    "name": "seller_stats",
    "description": "Get performance stats for a seller: listings, sales, revenue, top categories, avg days to sell.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "seller_id": {
                "type": "string",
                "description": "The seller ID to look up.",
            },
        },
        "required": ["seller_id"],
    },
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}


# ===========================================================================
# Handlers
# ===========================================================================

async def handle_search_inventory(
    query: str = "",
    category: str = "",
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    condition: str = "",
    **kwargs,
) -> Dict[str, Any]:
    """Search inventory with optional Serper market context enrichment."""
    items = _get_items_or_mock()

    # Filter
    results = []
    query_lower = query.lower()
    cond_rank = {c: i for i, c in enumerate(_CONDITIONS)}  # excellent=0, poor=3

    for item in items:
        if item.get("status", "active") != "active":
            continue
        if query_lower:
            searchable = " ".join([
                item.get("title", ""),
                item.get("description", ""),
                item.get("provenance", ""),
            ]).lower()
            if query_lower not in searchable:
                continue
        if category and item.get("category", "") != category:
            continue
        price = float(item.get("price", 0))
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        if condition:
            item_cond = item.get("condition", "")
            if cond_rank.get(item_cond, 99) > cond_rank.get(condition, 0):
                continue
        results.append({
            "id": item["id"],
            "title": item.get("title", ""),
            "price": item.get("price", 0),
            "condition": item.get("condition", ""),
            "category": item.get("category", ""),
            "seller_id": item.get("seller_id", ""),
            "listed_at": item.get("listed_at", ""),
            "thumbnail_url": item.get("thumbnail_url", ""),
        })

    # Serper enrichment: add market context for the search query
    market_context: Dict[str, Any] = {}
    if query:
        try:
            from middleware.serper_connector import get_serper
            serper = get_serper()
            if serper.should_enrich("search_inventory"):
                enriched = await serper.enrich(
                    f"vintage {query} sold price",
                    context_hint="resale market price",
                )
                if enriched.get("enriched"):
                    market_context = {
                        "web_snippets": enriched.get("snippets", [])[:3],
                        "web_links": enriched.get("links", [])[:3],
                    }
        except Exception:
            logger.debug("search_inventory: serper enrichment failed", exc_info=True)

    response: Dict[str, Any] = {
        "count": len(results),
        "items": results,
    }
    if market_context:
        response["market_context"] = market_context

    return _mcp_json(response)


async def handle_get_item(item_id: str = "", **kwargs) -> Dict[str, Any]:
    """Return full item record by ID."""
    items = _get_items_or_mock()
    item = _find_item(items, item_id)
    if not item:
        return _mcp_result(f"Item not found: {item_id}")
    return _mcp_json(item)


async def handle_get_price_comps(
    title: str = "",
    category: str = "",
    condition: str = "",
    **kwargs,
) -> Dict[str, Any]:
    """
    Get comparable sold prices.  Always calls Serper for real web data.
    Also checks local signal store for platform-specific price signals.
    """
    # --- Local platform comps from signal store ---
    local_comps: List[Dict[str, Any]] = []
    # Check items marked sold in our inventory
    items = _load_inventory()
    for item in items:
        if item.get("status") != "sold":
            continue
        if category and item.get("category", "") != category:
            continue
        title_lower = title.lower()
        item_title_lower = item.get("title", "").lower()
        # Simple relevance: share at least one significant word
        title_words = {w for w in title_lower.split() if len(w) > 3}
        if any(w in item_title_lower for w in title_words):
            local_comps.append({
                "source": "platform",
                "price": item.get("sold_price", item.get("price", 0)),
                "date": item.get("sold_at", item.get("listed_at", "")),
                "url": "",
                "title": item.get("title", ""),
            })

    # --- Serper web comps (always attempted) ---
    web_comps: List[Dict[str, Any]] = []
    snippets: List[str] = []
    try:
        from middleware.serper_connector import get_serper
        serper = get_serper()
        # get_price_comps always enriches regardless of SERPER_TOOLS setting
        enriched = await serper.enrich(
            f"{title} {category} {condition} sold price vintage resale eBay",
            context_hint="comparable sales",
        )
        if enriched.get("enriched"):
            snippets = enriched.get("snippets", [])
            for link in enriched.get("links", []):
                web_comps.append({
                    "source": "web",
                    "price": None,  # would need NLP to extract; left for caller
                    "date": "",
                    "url": link.get("url", ""),
                    "title": link.get("title", ""),
                })
    except Exception:
        logger.debug("get_price_comps: serper failed", exc_info=True)

    all_comps = local_comps + web_comps

    # Derive price range from local comps (web prices need extraction)
    local_prices = [c["price"] for c in local_comps if c.get("price")]
    suggested: Dict[str, Any] = {}
    if local_prices:
        local_prices.sort()
        low = local_prices[0]
        high = local_prices[-1]
        median = local_prices[len(local_prices) // 2]
        suggested = {"low": low, "high": high, "median": median}
    else:
        suggested = {"low": None, "high": None, "median": None,
                     "note": "Insufficient local sales data; check web comps"}

    result = {
        "query": {"title": title, "category": category, "condition": condition},
        "comparable_sales": all_comps,
        "suggested_price_range": suggested,
        "market_trend": "stable",  # would require time-series analysis; placeholder
        "web_context": snippets[:5],
        "data_sources": {
            "platform_comps": len(local_comps),
            "web_comps": len(web_comps),
        },
    }
    return _mcp_json(result)


async def handle_trending_now(limit: int = 10, **kwargs) -> Dict[str, Any]:
    """Return trending search terms and top categories from local signal data."""
    try:
        from middleware.signal_capture import get_signal_capture
        sc = get_signal_capture()
        trending_terms = sc.get_trending(n=limit)
        stats = sc.get_signal_stats()

        # Derive top categories from top tools / terms (heuristic)
        # For category trending, we'd need category tagged in signals.
        # Use top search terms as proxy.
        result = {
            "trending_searches": trending_terms,
            "top_categories": _top_categories_from_inventory(),
            "total_searches_7d": sum(t["count"] for t in trending_terms),
            "signal_stats": stats,
        }
    except Exception:
        logger.debug("trending_now: signal_capture failed", exc_info=True)
        result = {
            "trending_searches": [],
            "top_categories": _top_categories_from_inventory(),
            "total_searches_7d": 0,
            "signal_stats": {},
        }

    return _mcp_json(result)


def _top_categories_from_inventory() -> List[Dict[str, Any]]:
    """Count active items per category."""
    items = _get_items_or_mock()
    counts: Dict[str, int] = {}
    for item in items:
        if item.get("status", "active") == "active":
            cat = item.get("category", "other")
            counts[cat] = counts.get(cat, 0) + 1
    return [
        {"category": cat, "active_listings": cnt}
        for cat, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True)
    ]


async def handle_create_listing(
    title: str = "",
    description: str = "",
    price: float = 0.0,
    category: str = "other",
    condition: str = "good",
    photos: Optional[List[str]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Create a new item listing and persist to inventory store."""
    if not title or not description:
        return _mcp_result("Error: title and description are required.")
    if price <= 0:
        return _mcp_result("Error: price must be greater than 0.")

    item_id = f"item_{uuid.uuid4().hex[:8]}"
    now = _now()
    new_item = {
        "id": item_id,
        "title": title,
        "description": description,
        "price": price,
        "category": category,
        "condition": condition,
        "seller_id": "seller_unknown",  # would be set from auth context in production
        "listed_at": now,
        "status": "active",
        "thumbnail_url": photos[0] if photos else "",
        "photos": photos or [],
        "measurements": {},
        "provenance": "",
    }

    items = _load_inventory()
    if not items:
        items = _mock_items()  # initialise store with mock data on first real write
    items.append(new_item)
    _save_inventory(items)

    result = {
        "item_id": item_id,
        "listing_url": f"/items/{item_id}",
        "created_at": now,
        "status": "active",
    }
    return _mcp_json(result)


async def handle_update_listing(
    item_id: str = "",
    price: Optional[float] = None,
    description: Optional[str] = None,
    condition: Optional[str] = None,
    status: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Update a listing's price, description, condition, or status."""
    if not item_id:
        return _mcp_result("Error: item_id is required.")

    items = _get_items_or_mock()
    item = _find_item(items, item_id)
    if not item:
        return _mcp_result(f"Error: item not found: {item_id}")

    if price is not None:
        item["price"] = price
    if description is not None:
        item["description"] = description
    if condition is not None:
        item["condition"] = condition
    if status is not None:
        item["status"] = status

    item["updated_at"] = _now()
    _save_inventory(items)
    return _mcp_json(item)


async def handle_mark_sold(
    item_id: str = "",
    sold_price: float = 0.0,
    buyer_note: str = "",
    **kwargs,
) -> Dict[str, Any]:
    """
    Mark an item as sold.  Records actual sold price for price signal data.
    This is the most important write operation for the data flywheel.
    """
    if not item_id:
        return _mcp_result("Error: item_id is required.")
    if sold_price <= 0:
        return _mcp_result("Error: sold_price must be greater than 0.")

    items = _get_items_or_mock()
    item = _find_item(items, item_id)
    if not item:
        return _mcp_result(f"Error: item not found: {item_id}")

    if item.get("status") == "sold":
        return _mcp_result(f"Item {item_id} is already marked as sold.")

    now = _now()
    item["status"] = "sold"
    item["sold_price"] = sold_price
    item["sold_at"] = now
    if buyer_note:
        item["buyer_note"] = buyer_note

    _save_inventory(items)

    result = {
        "confirmed": True,
        "item_id": item_id,
        "sold_price": sold_price,
        "sold_at": now,
        "title": item.get("title", ""),
        "listed_price": item.get("price", 0),
        "price_delta": round(sold_price - float(item.get("price", 0)), 2),
    }
    return _mcp_json(result)


async def handle_seller_stats(seller_id: str = "", **kwargs) -> Dict[str, Any]:
    """Aggregate performance stats for a seller."""
    if not seller_id:
        return _mcp_result("Error: seller_id is required.")

    items = _get_items_or_mock()
    seller_items = [i for i in items if i.get("seller_id") == seller_id]

    if not seller_items:
        return _mcp_json({
            "seller_id": seller_id,
            "total_listed": 0,
            "total_sold": 0,
            "avg_price": 0,
            "total_revenue": 0.0,
            "top_categories": [],
            "avg_days_to_sell": None,
            "message": "No listings found for this seller.",
        })

    sold_items = [i for i in seller_items if i.get("status") == "sold"]
    all_prices = [float(i.get("price", 0)) for i in seller_items]
    avg_price = round(sum(all_prices) / len(all_prices), 2) if all_prices else 0.0
    total_revenue = round(sum(float(i.get("sold_price", i.get("price", 0))) for i in sold_items), 2)

    # Category breakdown
    cat_counts: Dict[str, int] = {}
    for item in seller_items:
        cat = item.get("category", "other")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    top_categories = [
        {"category": c, "count": n}
        for c, n in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    # Average days to sell (items with both listed_at and sold_at)
    days_to_sell_list: List[float] = []
    for item in sold_items:
        try:
            listed = datetime.fromisoformat(item["listed_at"])
            sold = datetime.fromisoformat(item["sold_at"])
            days_to_sell_list.append((sold - listed).days)
        except (KeyError, ValueError):
            continue
    avg_days = round(sum(days_to_sell_list) / len(days_to_sell_list), 1) if days_to_sell_list else None

    result = {
        "seller_id": seller_id,
        "total_listed": len(seller_items),
        "total_sold": len(sold_items),
        "avg_price": avg_price,
        "total_revenue": total_revenue,
        "top_categories": top_categories,
        "avg_days_to_sell": avg_days,
    }
    return _mcp_json(result)


# ===========================================================================
# Exports
# ===========================================================================

TOOLS = [
    SEARCH_INVENTORY_TOOL,
    GET_ITEM_TOOL,
    GET_PRICE_COMPS_TOOL,
    TRENDING_NOW_TOOL,
    CREATE_LISTING_TOOL,
    UPDATE_LISTING_TOOL,
    MARK_SOLD_TOOL,
    SELLER_STATS_TOOL,
]

HANDLERS: Dict[str, Any] = {
    "search_inventory": handle_search_inventory,
    "get_item": handle_get_item,
    "get_price_comps": handle_get_price_comps,
    "trending_now": handle_trending_now,
    "create_listing": handle_create_listing,
    "update_listing": handle_update_listing,
    "mark_sold": handle_mark_sold,
    "seller_stats": handle_seller_stats,
}
