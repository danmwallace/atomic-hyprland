#!/usr/bin/python3
"""In-image: python3 /tests/mcp-smoke.py [--text-only] <server> <tool>... — the server
starts over stdio and lists every named tool. Exit 1 if one is missing.

--text-only also fails if a named tool declares an outputSchema: Claude Code reads a
permission-prompt tool's answer from a single text block and rejects a structured result
("Permission prompt tool returned an invalid result")."""
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def tools(server: str) -> dict:
    params = StdioServerParameters(command="/usr/libexec/atomic-hyprland/mcp-server", args=[server])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return {t.name: t for t in (await s.list_tools()).tools}


args = sys.argv[1:]
text_only = args[:1] == ["--text-only"]
if text_only:
    args = args[1:]
server, wanted = args[0], args[1:]
have = asyncio.run(tools(server))
missing = sorted(set(wanted) - set(have))
structured = sorted(n for n in wanted if text_only and n in have and have[n].outputSchema)
print(f"{server}: {sorted(have)}" + (f" missing {missing}" if missing else "")
      + (f" structured output {structured}" if structured else ""))
sys.exit(1 if missing or structured else 0)
