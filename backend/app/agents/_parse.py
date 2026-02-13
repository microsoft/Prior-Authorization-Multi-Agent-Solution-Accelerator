"""Shared JSON response parser for agent outputs."""

import json


def parse_json_response(response) -> dict:
    """Extract JSON from an agent response, with fallback.

    Searches for the outermost JSON object in the response text.
    Returns parsed dict on success, or an error dict on failure.
    """
    try:
        text = response.text if hasattr(response, "text") else str(response)
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            return json.loads(text[json_start:json_end])
    except (json.JSONDecodeError, AttributeError):
        pass
    return {"error": "Could not parse agent response as JSON", "raw": str(response)}
