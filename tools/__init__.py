"""
Tool Registry for vintage-resale-mcp.

Exposes the real resale tools as ALL_TOOLS / ALL_HANDLERS.
The example tools (tools/example.py) are kept as reference but are not
exposed in production — they are not registered here.

To add a new tool module:
    1. Create tools/my_tools.py with TOOLS list and HANDLERS dict
    2. Import and extend below
"""

from typing import Dict, List, Any, Callable, Coroutine

from tools.resale import TOOLS as RESALE_TOOLS, HANDLERS as RESALE_HANDLERS

# ---------------------------------------------------------------------------
# Aggregate all tool definitions and handler functions
# ---------------------------------------------------------------------------

ALL_TOOLS: List[Dict[str, Any]] = [
    *RESALE_TOOLS,
    # Add more tool lists here as you create new modules:
    # *MY_TOOLS,
]

ALL_HANDLERS: Dict[str, Callable[..., Coroutine]] = {
    **RESALE_HANDLERS,
    # Add more handler dicts here:
    # **MY_HANDLERS,
}
