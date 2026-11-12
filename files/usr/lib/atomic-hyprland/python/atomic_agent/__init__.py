"""atomic-hyprland's agentic desktop: the hotkey agent, its approvals and undo,
the desktop MCP servers and the MCP drop-in registry.

Logic lives in plain functions so the host tests run without python3-mcp;
modules under servers/ import mcp only inside main().
"""
