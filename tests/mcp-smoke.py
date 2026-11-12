#!/usr/bin/python3
"""In-image: python3 /tests/mcp-smoke.py <server> <tool>... — the server starts over
stdio and lists every named tool. Exit 1 if one is missing."""
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def tools(server: str) -> set[str]:
    params = StdioServerParameters(command="/usr/libexec/atomic-hyprland/mcp-server", args=[server])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return {t.name for t in (await s.list_tools()).tools}


have = asyncio.run(tools(sys.argv[1]))
missing = sorted(set(sys.argv[2:]) - have)
print(f"{sys.argv[1]}: {sorted(have)}" + (f" missing {missing}" if missing else ""))
sys.exit(1 if missing else 0)
