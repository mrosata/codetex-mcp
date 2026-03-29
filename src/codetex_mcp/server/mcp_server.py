"""MCP server — stdio transport entry point.

Tools will be registered in US-020. This module provides the server
factory used by ``codetex serve``.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def create_server() -> FastMCP:
    """Create and return the FastMCP server instance."""
    server = FastMCP("codetex")
    return server
