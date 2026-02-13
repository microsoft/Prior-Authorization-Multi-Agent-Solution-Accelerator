"""Dump all tool schemas from working MCP servers."""

import asyncio
import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SERVERS = {
    "NPI Registry": "https://mcp.deepsense.ai/npi_registry/mcp",
    "ICD-10 Codes": "https://mcp.deepsense.ai/icd10_codes/mcp",
    "CMS Coverage": "https://mcp.deepsense.ai/cms_coverage/mcp",
}

HEADERS = {"User-Agent": "claude-code/1.0"}


async def dump_tools(name: str, url: str):
    print(f"\n{'='*65}")
    print(f"SERVER: {name}")
    print(f"{'='*65}")
    async with streamablehttp_client(url, headers=HEADERS) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            for t in tools.tools:
                print(f"\n  TOOL: {t.name}")
                desc = (t.description or "").encode("ascii", "replace").decode()
                print(f"  Desc: {desc[:200]}")
                print(f"  Schema: {json.dumps(t.inputSchema, indent=4)}")


async def main():
    for name, url in SERVERS.items():
        await dump_tools(name, url)


if __name__ == "__main__":
    asyncio.run(main())
