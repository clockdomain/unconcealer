"""MCP server module for Claude Desktop integration.

This module provides the stdio-based MCP server that Claude Desktop
can spawn and communicate with for embedded debugging.

Example:
    # From command line:
    unconcealer mcp-server

    # In Claude Desktop config:
    {
      "mcpServers": {
        "embedded-debugger": {
          "command": "unconcealer",
          "args": ["mcp-server"]
        }
      }
    }
"""

from unconcealer.mcp.session_manager import SessionManager
from unconcealer.mcp.stdio_server import run_stdio_server

__all__ = [
    "SessionManager",
    "run_stdio_server",
]
