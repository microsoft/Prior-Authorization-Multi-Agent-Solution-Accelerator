"""Test: MS Agent Framework MCPStreamableHTTPTool with custom User-Agent header.

This tests whether we can use the Agent Framework's built-in MCP tool
with a pre-configured httpx.AsyncClient to inject the User-Agent header,
instead of writing our own MCPClient.

No Claude model needed — this just tests the MCP connection layer.
"""

import asyncio
import httpx
from agent_framework import MCPStreamableHTTPTool


# The magic header
HTTP_CLIENT = httpx.AsyncClient(headers={"User-Agent": "claude-code/1.0"})

# MCP servers to test
SERVERS = {
    "npi-registry": "https://mcp.deepsense.ai/npi_registry/mcp",
    "icd10-codes": "https://mcp.deepsense.ai/icd10_codes/mcp",
    "cms-coverage": "https://mcp.deepsense.ai/cms_coverage/mcp",
}


async def test_single(label: str, url: str) -> bool:
    """Test a single MCP server: connect, list tools, call one."""
    print(f"\n{'='*55}")
    print(f"Testing: {label} ({url})")
    print(f"{'='*55}")

    mcp_tool = MCPStreamableHTTPTool(
        name=label,
        url=url,
        http_client=HTTP_CLIENT,
    )

    try:
        async with mcp_tool:
            # List tools (stored in _functions after load_tools)
            tools = mcp_tool._functions
            print(f"  Connected! Found {len(tools)} tools:")
            for t in tools:
                print(f"    - {t.name}")

            # Try calling a tool based on the server
            if label == "npi-registry":
                print("\n  Calling npi_validate('1234567893')...")
                result = await mcp_tool.session.call_tool(
                    "npi_validate", {"npi": "1234567893"}
                )
            elif label == "icd10-codes":
                print("\n  Calling validate_code('E11.65', 'diagnosis')...")
                result = await mcp_tool.session.call_tool(
                    "validate_code", {"code": "E11.65", "code_type": "diagnosis"}
                )
            elif label == "cms-coverage":
                print("\n  Calling search_national_coverage('knee')...")
                result = await mcp_tool.session.call_tool(
                    "search_national_coverage", {"keyword": "knee", "document_type": "ncd", "limit": 3}
                )
            else:
                print("  (no test call defined)")
                return True

            # Parse result
            texts = [b.text for b in result.content if hasattr(b, "text")]
            preview = " ".join(texts)[:200]
            print(f"  Result: {preview}")
            return True

    except Exception as e:
        print(f"  ERROR: {e}")
        return False


async def main():
    print("MS Agent Framework MCPStreamableHTTPTool Test")
    print("Header: User-Agent: claude-code/1.0")

    results = {}
    for label, url in SERVERS.items():
        ok = await test_single(label, url)
        results[label] = "PASS" if ok else "FAIL"

    print(f"\n{'='*55}")
    print("SUMMARY")
    print(f"{'='*55}")
    all_pass = True
    for name, status in results.items():
        marker = "OK" if status == "PASS" else "XX"
        print(f"  [{marker}] {name}: {status}")
        if status != "PASS":
            all_pass = False

    if all_pass:
        print("\nAll servers work via Agent Framework MCPStreamableHTTPTool!")
    else:
        print("\nSome servers failed.")

    await HTTP_CLIENT.aclose()


if __name__ == "__main__":
    asyncio.run(main())
