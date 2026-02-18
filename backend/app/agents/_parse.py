"""Shared JSON response parser for agent outputs."""

import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_json_response(response) -> dict:
    """Extract JSON from an agent response, with fallback.

    The agent response may contain interleaved tool-call results and
    explanatory text before / after the final JSON object.  This parser
    tries multiple strategies in order of reliability:

    1. JSON inside a markdown code fence (```json ... ``` or ``` ... ```)
    2. Brace-matched extraction working **backwards** from the last ``}``
       — this finds the outermost JSON object that ends at the very end
       of the response, which is almost always the final answer.
    3. Legacy first-``{`` to last-``}`` substring (original approach).

    Returns parsed dict on success, or an error dict on failure.
    """
    try:
        text = response.text if hasattr(response, "text") else str(response)
    except Exception:
        text = str(response)

    if not text or not text.strip():
        return {"error": "Agent returned empty response", "raw": ""}

    # --- Strategy 1: markdown code fence ---
    # Match the LAST fenced JSON block (most likely the final answer)
    fence_pattern = re.compile(
        r"```(?:json)?\s*\n(\{.*?\})\s*\n```",
        re.DOTALL,
    )
    fences = fence_pattern.findall(text)
    if fences:
        # Try the last fence first (most likely the final JSON answer)
        for candidate in reversed(fences):
            parsed = _try_parse(candidate)
            if parsed is not None:
                return parsed

    # --- Strategy 2: brace-matched, working backward from last ``}`` ---
    parsed = _extract_last_json_object(text)
    if parsed is not None:
        return parsed

    # --- Strategy 3: legacy first-{ to last-} (fallback) ---
    json_start = text.find("{")
    json_end = text.rfind("}") + 1
    if json_start != -1 and json_end > json_start:
        parsed = _try_parse(text[json_start:json_end])
        if parsed is not None:
            return parsed

    # --- All strategies failed ---
    # Log a snippet for debugging (truncate to avoid flooding logs)
    snippet = text[:500] + ("..." if len(text) > 500 else "")
    logger.error("Could not parse agent response as JSON. Snippet: %s", snippet)
    return {"error": "Could not parse agent response as JSON", "raw": snippet}


def _try_parse(text: str) -> dict | None:
    """Attempt to parse *text* as JSON.  Returns dict or None."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _extract_last_json_object(text: str) -> dict | None:
    """Find the last complete top-level JSON object in *text*.

    Walks backward from the final ``}`` and counts braces to locate
    the matching ``{``.  Handles nested objects, strings (including
    escaped quotes), and ignores braces inside string literals.
    """
    end = text.rfind("}")
    if end == -1:
        return None

    # Walk backward counting braces, respecting string boundaries
    depth = 0
    in_string = False
    i = end
    while i >= 0:
        ch = text[i]

        if in_string:
            if ch == '"':
                # Check if this quote is escaped
                num_backslashes = 0
                j = i - 1
                while j >= 0 and text[j] == "\\":
                    num_backslashes += 1
                    j -= 1
                if num_backslashes % 2 == 0:
                    in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "}":
                depth += 1
            elif ch == "{":
                depth -= 1
                if depth == 0:
                    # Found matching opening brace
                    candidate = text[i : end + 1]
                    parsed = _try_parse(candidate)
                    if parsed is not None:
                        return parsed
                    # If parse failed, keep searching backward
                    # for an earlier { that might be the real start
                    depth = 1  # reset — we still haven't closed the }

        i -= 1

    return None
