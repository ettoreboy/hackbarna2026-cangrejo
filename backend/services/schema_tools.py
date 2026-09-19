"""Turn a Pydantic JSON schema into one an OpenAI-compatible strict mode will accept.

Strict structured output (OpenAI spec, which Nebius Token Factory implements) is narrower
than JSON Schema:

- every object needs ``additionalProperties: false``
- every property must be listed in ``required``
- numeric and string validation keywords (minimum, maxLength, pattern, format ...) are not
  part of the subset and are rejected or silently ignored depending on the engine

Pydantic emits all of those, so the schema is sanitised before it goes on the wire. The
constraints stay on the Pydantic model, which still validates whatever comes back.

Observed live: the engine does not surface ``description`` to the model under strict mode.
Field semantics therefore belong in the prompt text (see backend/prompts/).
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel

_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minItems",
        "maxItems",
        "uniqueItems",
        "default",
        "examples",
    }
)


def _walk(node: Any) -> Any:
    if isinstance(node, list):
        return [_walk(item) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _UNSUPPORTED_KEYWORDS:
            continue
        out[key] = _walk(value)

    if out.get("type") == "object" or "properties" in out:
        out.setdefault("properties", {})
        out["additionalProperties"] = False
        out["required"] = list(out["properties"].keys())
    return out


def to_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Sanitised deep copy of ``schema``, safe to send as a strict json_schema."""
    return _walk(copy.deepcopy(schema))


def response_format_strict(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """The wrapped form: {"type": "json_schema", "json_schema": {name, strict, schema}}."""
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": to_strict_schema(schema)},
    }


RESPONSE_FORMAT_JSON_OBJECT: dict[str, Any] = {"type": "json_object"}


def schema_reminder(model_cls: type[BaseModel]) -> str:
    """One-line key list for the json_object fallback, where only 'valid JSON' is enforced."""

    def describe(props: dict[str, Any], defs: dict[str, Any]) -> str:
        parts = []
        for key, spec in props.items():
            if "$ref" in spec:
                ref = defs[spec["$ref"].split("/")[-1]]
                parts.append(f"{key} (object with {describe(ref.get('properties', {}), defs)})")
            elif spec.get("type") == "array" and "$ref" in spec.get("items", {}):
                ref = defs[spec["items"]["$ref"].split("/")[-1]]
                parts.append(f"{key} (array of objects with {describe(ref.get('properties', {}), defs)})")
            elif "enum" in spec:
                parts.append(f"{key} (one of {', '.join(map(str, spec['enum']))})")
            else:
                parts.append(f"{key} ({spec.get('type', 'string')})")
        return ", ".join(parts)

    schema = model_cls.model_json_schema()
    return (
        "\nReturn a single JSON object with exactly these keys: "
        + describe(schema.get("properties", {}), schema.get("$defs", {}))
        + ". No prose outside the JSON."
    )
