"""Shared JSON response parser for agent outputs."""

import json
import logging
import re
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def pydantic_to_output_format(
    model_class: type[BaseModel],
    exclude_fields: tuple[str, ...] = ("agent_name", "checks_performed"),
) -> dict[str, Any]:
    """Convert a Pydantic model class to a ClaudeAgent output_format dict.

    The agent framework's ``output_format`` option accepts::

        {"type": "json_schema", "schema": <JSON Schema dict>}

    This helper generates the schema from the Pydantic model using
    ``model_json_schema()``, which handles nested models, ``$defs``,
    ``$ref``, Optional fields, and defaults automatically.

    The schema is made **strict** by adding ``additionalProperties: false``
    and explicit ``required`` lists at every object level.  This ensures
    the LLM cannot invent custom field names or nest data in ad-hoc
    wrappers — the output must conform exactly to the Pydantic model.

    ``exclude_fields`` strips UI-only fields (e.g. ``agent_name``,
    ``checks_performed``) from the schema so the LLM focuses on
    domain-specific fields rather than dumping data into flexible
    catch-all arrays.  These fields are regenerated post-hoc in the
    response builder.

    Usage::

        from app.models.schemas import ComplianceResult
        agent = ClaudeAgent(
            instructions="...",
            default_options={
                "output_format": pydantic_to_output_format(ComplianceResult),
            },
        )
    """
    import copy

    schema = copy.deepcopy(model_class.model_json_schema())

    # Strip UI-only fields from schema properties and required list
    props = schema.get("properties", {})
    for field in exclude_fields:
        props.pop(field, None)
    req = schema.get("required", [])
    if req:
        schema["required"] = [r for r in req if r not in exclude_fields]

    # Remove unused $defs that only served excluded fields
    defs = schema.get("$defs", {})
    if defs and exclude_fields:
        # Collect all $ref references still used in the schema
        schema_str = json.dumps(schema)
        unused = [
            name for name in list(defs.keys())
            if f'"$ref": "#/$defs/{name}"' not in schema_str
            and f'"$defs/{name}"' not in schema_str
        ]
        for name in unused:
            defs.pop(name, None)
        if not defs:
            schema.pop("$defs", None)

    # --- Make the schema strict ---
    # Add additionalProperties: false and required lists at every
    # object level so the LLM cannot invent custom field names.
    _make_strict(schema)

    return {
        "type": "json_schema",
        "schema": schema,
    }


def _make_strict(schema: dict) -> None:
    """Recursively add ``additionalProperties: false`` and ``required``
    to every object-type node in a JSON Schema so structured output
    is enforced strictly.

    Also walks into ``$defs``, ``items``, and ``anyOf`` branches.
    """
    if not isinstance(schema, dict):
        return

    # Process $defs first (nested model definitions)
    for _def in schema.get("$defs", {}).values():
        _make_strict(_def)

    # If this node is an object with properties, enforce strictness
    if schema.get("type") == "object" and "properties" in schema:
        schema["additionalProperties"] = False
        # Build required list from all property names (if not already set)
        if "required" not in schema:
            schema["required"] = list(schema["properties"].keys())

    # Recurse into each property value
    for prop_schema in schema.get("properties", {}).values():
        _make_strict(prop_schema)

    # Recurse into items (array elements)
    items = schema.get("items")
    if isinstance(items, dict):
        _make_strict(items)

    # Recurse into anyOf / oneOf branches (used for Optional types)
    for branch_key in ("anyOf", "oneOf"):
        for branch in schema.get(branch_key, []):
            if isinstance(branch, dict):
                _make_strict(branch)


def parse_json_response(response) -> dict:
    """Extract JSON from an agent response, with fallback.

    Strategy 0 (preferred): If the response carries ``structured_output``
    (set automatically when the agent was created with ``output_format``),
    return it directly — no text parsing or sanitization needed.

    Fallback strategies for text-based responses:

    1. JSON inside a markdown code fence (```json ... ``` or ``` ... ```)
    2. Brace-matched extraction working **backwards** from the last ``}``
       — this finds the outermost JSON object that ends at the very end
       of the response, which is almost always the final answer.
    3. Legacy first-``{`` to last-``}`` substring (original approach).

    Each strategy also tries a JSON cleanup pass (trailing commas,
    single-line comments) if the initial parse fails.

    Returns parsed dict on success, or an error dict on failure.
    """
    # --- Strategy 0: structured output (from output_format option) ---
    # Check both response.structured_output (legacy) and response.value
    # (MAF >= 1.0.0b260225 / PR #4137 propagates structured_output via
    # AgentResponse.value).
    so = None
    if hasattr(response, "structured_output") and response.structured_output is not None:
        so = response.structured_output
        logger.info("[parse] Strategy 0: found structured_output attr")
    elif hasattr(response, "value") and response.value is not None:
        so = response.value
        logger.info("[parse] Strategy 0: found response.value (PR #4137)")

    if so is not None:
        if isinstance(so, dict):
            logger.info("[parse] Strategy 0: structured output (dict, %d keys)", len(so))
            return so
        if isinstance(so, str):
            try:
                parsed = json.loads(so)
                if isinstance(parsed, dict):
                    logger.info("[parse] Strategy 0: structured output (parsed string, %d keys)", len(parsed))
                    return parsed
            except json.JSONDecodeError:
                pass
        if hasattr(so, "model_dump"):
            dumped = so.model_dump()
            logger.info("[parse] Strategy 0: structured output (Pydantic model, %d keys)", len(dumped))
            return dumped
        logger.warning("[parse] Strategy 0: structured output present but unusable (type=%s)", type(so).__name__)

    # --- Diagnostic logging ---
    logger.info(
        "[parse] response type=%s, has .text=%s",
        type(response).__name__,
        hasattr(response, "text"),
    )

    try:
        text = response.text if hasattr(response, "text") else str(response)
    except Exception:
        text = str(response)

    text_len = len(text) if text else 0
    logger.info("[parse] text length=%d", text_len)
    if text and text_len > 0:
        logger.info("[parse] first 300 chars: %s", text[:300])
        if text_len > 300:
            logger.info("[parse] last 300 chars: %s", text[-300:])

    if not text or not text.strip():
        logger.error("[parse] Agent returned empty response")
        return {"error": "Agent returned empty response", "raw": ""}

    # --- Strategy 1: markdown code fence ---
    # Match the LAST fenced JSON block (most likely the final answer)
    # Two patterns: strict (with newlines) and relaxed (without)
    fence_patterns = [
        re.compile(r"```(?:json)?\s*\n(\{.*?\})\s*\n```", re.DOTALL),
        re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL),
    ]
    for pat_idx, fence_pattern in enumerate(fence_patterns):
        fences = fence_pattern.findall(text)
        if fences:
            logger.info("[parse] Strategy 1 (fence pattern %d): found %d fences", pat_idx, len(fences))

            # If multiple fences found, try to merge all valid JSON dicts.
            # Agents often split output across multiple ```json blocks
            # (e.g., code_validation, clinical_extraction, procedure_assessment).
            # Merging gives a complete result instead of just the last block.
            if len(fences) > 1:
                merged = {}
                merge_count = 0
                for candidate in fences:
                    parsed = _try_parse(candidate)
                    if parsed is None:
                        parsed = _try_parse(_cleanup_json(candidate))
                    if parsed is not None:
                        merged.update(parsed)
                        merge_count += 1
                if merged and merge_count > 1:
                    logger.info("[parse] Strategy 1: merged %d/%d fence blocks into %d keys",
                                merge_count, len(fences), len(merged))
                    return merged

            # Single fence or merge didn't work — fall back to last-fence
            for idx, candidate in enumerate(reversed(fences)):
                parsed = _try_parse(candidate)
                if parsed is not None:
                    logger.info("[parse] Strategy 1 succeeded (pattern %d, fence #%d from end)", pat_idx, idx)
                    return parsed
                # Try with cleanup
                parsed = _try_parse(_cleanup_json(candidate))
                if parsed is not None:
                    logger.info("[parse] Strategy 1 succeeded after cleanup (pattern %d, fence #%d from end)", pat_idx, idx)
                    return parsed
                logger.info("[parse] Strategy 1 fence #%d from end failed to parse (%d chars)", idx, len(candidate))

    logger.info("[parse] Strategy 1: no fences found or none parsed")

    # --- Strategy 2: brace-matched, working backward from last ``}`` ---
    parsed = _extract_last_json_object(text)
    if parsed is not None:
        logger.info("[parse] Strategy 2 (brace-match backward) succeeded")
        return parsed
    logger.info("[parse] Strategy 2 (brace-match backward) failed")

    # --- Strategy 3: legacy first-{ to last-} (fallback) ---
    json_start = text.find("{")
    json_end = text.rfind("}") + 1
    if json_start != -1 and json_end > json_start:
        candidate = text[json_start:json_end]
        logger.info("[parse] Strategy 3: trying text[%d:%d] (%d chars)", json_start, json_end, len(candidate))
        parsed = _try_parse(candidate)
        if parsed is not None:
            logger.info("[parse] Strategy 3 (legacy first-to-last brace) succeeded")
            return parsed
        # Try with cleanup
        parsed = _try_parse(_cleanup_json(candidate))
        if parsed is not None:
            logger.info("[parse] Strategy 3 succeeded after cleanup")
            return parsed
        logger.info("[parse] Strategy 3 failed to parse")
    else:
        logger.info("[parse] Strategy 3: no braces found (start=%d, end=%d)", json_start, json_end - 1)

    # --- All strategies failed ---
    snippet = text[:500] + ("..." if len(text) > 500 else "")
    logger.error("Could not parse agent response as JSON. Full length=%d. Snippet: %s", text_len, snippet)
    return {
        "error": "Could not parse agent response as JSON",
        "raw": snippet,
        "text_length": text_len,
    }


def _cleanup_json(text: str) -> str:
    """Attempt to fix common JSON issues produced by LLM agents.

    Handles:
    - Trailing commas before } or ]
    - Single-line comments (// ...)
    - Unquoted NaN/Infinity values
    """
    # Remove single-line comments (but not inside strings — best effort)
    cleaned = re.sub(r'(?<!["\w])//[^\n]*', '', text)
    # Remove trailing commas before } or ]
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    return cleaned


def _try_parse(text: str) -> dict | None:
    """Attempt to parse *text* as JSON.  Returns dict or None."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        logger.info("[parse] _try_parse: parsed OK but not a dict (type=%s)", type(obj).__name__)
    except json.JSONDecodeError as e:
        logger.debug("[parse] _try_parse: JSONDecodeError at pos %d: %s", e.pos, e.msg)
    except (ValueError, TypeError) as e:
        logger.debug("[parse] _try_parse: %s: %s", type(e).__name__, e)
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
                    # Try with cleanup
                    parsed = _try_parse(_cleanup_json(candidate))
                    if parsed is not None:
                        logger.info("[parse] Strategy 2: succeeded after cleanup")
                        return parsed
                    # If parse failed, keep searching backward
                    # for an earlier { that might be the real start
                    depth = 1  # reset — we still haven't closed the }

        i -= 1

    return None
