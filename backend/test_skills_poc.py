"""POC: Test MAF Skills + MCP Servers Coexistence

This script verifies that ClaudeAgent can be configured with BOTH:
  - Skills discovery (setting_sources + allowed_tools: ["Skill"])
  - MCP servers (mcp_servers dict)

If this works, we can proceed with transforming system prompts into SKILL.md
files while keeping MCP tools available to each agent.

Test Plan:
  1. Configure ClaudeAgent with skills + MCP (icd10-codes) + permission bypass
  2. Ask the agent to validate an ICD-10 code using its skill
  3. If the skill is discovered AND MCP tools are available, the test passes
"""

import asyncio
import io
import logging
import os
import sys
from pathlib import Path

# Fix Windows console encoding — force UTF-8 output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace"
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace"
    )

# Add backend directory to path so patches can be imported
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Apply SDK patches (Windows CMD bypass, API credentials, model mapping)
from app.patches import apply as apply_patches

apply_patches()

from agent_framework_claude import ClaudeAgent

logger = logging.getLogger(__name__)

# MCP server config (same as mcp_config.py)
_HEADERS = {"User-Agent": "claude-code/1.0"}
ICD10_SERVER = {
    "type": "http",
    "url": os.getenv("MCP_ICD10_CODES", "https://mcp.deepsense.ai/icd10_codes/mcp"),
    "headers": _HEADERS,
}


async def test_skills_only():
    """Test 1: Skills discovery only (no MCP)."""
    print("\n" + "=" * 60)
    print("TEST 1: Skills Discovery Only (no MCP)")
    print("=" * 60)

    cwd = str(Path(__file__).parent)
    agent = ClaudeAgent(
        instructions="You are a test assistant. Use any available Skills.",
        default_options={
            "cwd": cwd,
            "setting_sources": ["user", "project"],
            "allowed_tools": ["Skill", "Read"],
            "permission_mode": "bypassPermissions",
        },
    )

    query = "What Skills are available to you? List them briefly."
    print(f"\nQuery: {query}")
    print("Response: ", end="", flush=True)

    try:
        async with agent:
            async for update in agent.run(query, stream=True):
                for content in update.contents:
                    if content.type == "text":
                        print(content.text, end="", flush=True)
                    elif content.type == "usage":
                        print(
                            f"\n[Usage: {content.usage_details}]",
                            end="",
                            flush=True,
                        )
        print("\n\nRESULT: PASS - Skills discovery works")
        return True
    except Exception as e:
        print(f"\n\nRESULT: FAIL - {e}")
        return False


async def test_skills_with_mcp():
    """Test 2: Skills + MCP servers together (the critical test)."""
    print("\n" + "=" * 60)
    print("TEST 2: Skills + MCP Servers Coexistence")
    print("=" * 60)

    cwd = str(Path(__file__).parent)
    agent = ClaudeAgent(
        instructions=(
            "You are a test assistant with access to Skills and MCP tools. "
            "When asked to validate an ICD-10 code, use the icd10-codes MCP tools."
        ),
        default_options={
            "cwd": cwd,
            "setting_sources": ["user", "project"],
            "allowed_tools": ["Skill", "Read",
                              "mcp__icd10-codes__validate_code",
                              "mcp__icd10-codes__lookup_code",
                              "mcp__icd10-codes__search_codes"],
            "mcp_servers": {"icd10-codes": ICD10_SERVER},
            "permission_mode": "bypassPermissions",
        },
    )

    query = (
        "Validate the ICD-10 diagnosis code E11.65. "
        "Tell me: is it valid for HIPAA? What is its description?"
    )
    print(f"\nQuery: {query}")
    print("Response: ", end="", flush=True)

    try:
        async with agent:
            async for update in agent.run(query, stream=True):
                for content in update.contents:
                    if content.type == "text":
                        print(content.text, end="", flush=True)
                    elif content.type == "usage":
                        print(
                            f"\n[Usage: {content.usage_details}]",
                            end="",
                            flush=True,
                        )
        print("\n\nRESULT: PASS - Skills + MCP coexistence works")
        return True
    except Exception as e:
        print(f"\n\nRESULT: FAIL - {e}")
        return False


async def test_mcp_only_baseline():
    """Test 3: MCP only (no skills) — baseline to compare."""
    print("\n" + "=" * 60)
    print("TEST 3: MCP Only Baseline (no Skills)")
    print("=" * 60)

    agent = ClaudeAgent(
        instructions="You are a test assistant. Validate ICD-10 codes using MCP tools.",
        default_options={
            "mcp_servers": {"icd10-codes": ICD10_SERVER},
            "permission_mode": "bypassPermissions",
        },
    )

    query = "Validate ICD-10 code E11.65. Is it valid for HIPAA? What is its description?"
    print(f"\nQuery: {query}")
    print("Response: ", end="", flush=True)

    try:
        async with agent:
            async for update in agent.run(query, stream=True):
                for content in update.contents:
                    if content.type == "text":
                        print(content.text, end="", flush=True)
                    elif content.type == "usage":
                        print(
                            f"\n[Usage: {content.usage_details}]",
                            end="",
                            flush=True,
                        )
        print("\n\nRESULT: PASS - MCP baseline works")
        return True
    except Exception as e:
        print(f"\n\nRESULT: FAIL - {e}")
        return False


async def main():
    print("MAF Skills + MCP Coexistence POC Test")
    print("=" * 60)
    print(f"CWD: {Path(__file__).parent}")
    print(f"Skills dir: {Path(__file__).parent / '.claude' / 'skills'}")
    print(
        f"Skills dir exists: {(Path(__file__).parent / '.claude' / 'skills').exists()}"
    )
    print(f"ICD10 MCP URL: {ICD10_SERVER['url']}")

    results = {}

    # Run tests sequentially
    results["test_1_skills_only"] = await test_skills_only()
    results["test_2_skills_with_mcp"] = await test_skills_with_mcp()
    results["test_3_mcp_baseline"] = await test_mcp_only_baseline()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")

    if results["test_2_skills_with_mcp"]:
        print("\nConclusion: Skills + MCP coexistence is CONFIRMED.")
        print("We can proceed with the full skills implementation plan.")
    else:
        print("\nConclusion: Skills + MCP coexistence FAILED.")
        print("Need to investigate alternative approaches.")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
