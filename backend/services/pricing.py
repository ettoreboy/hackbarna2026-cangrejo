"""Token prices used for the cost column in eval tables.

Nebius publishes its rate card in the console (tokenfactory.nebius.com/organization/prices),
not in the public docs, so the table below is seeded with the values read from there and can
be overridden without touching code:

    NEBIUS_PRICES='{"Qwen/Qwen3-32B": [0.10, 0.30]}'   # USD per 1M tokens, [input, output]

An unknown model yields ``None`` rather than a wrong number: a missing cost column is honest,
an invented one is not.
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

# USD per 1M tokens: model id -> (input, output).
NEBIUS_PRICES: dict[str, tuple[float, float]] = {
    "Qwen/Qwen3-235B-A22B-Instruct-2507": (0.20, 0.60),
    "Qwen/Qwen3-235B-A22B": (0.20, 0.60),
    "Qwen/Qwen3-30B-A3B-Instruct-2507": (0.10, 0.30),
    "Qwen/Qwen3-32B": (0.10, 0.30),
    "Qwen/Qwen3-14B": (0.07, 0.21),
    "Qwen/Qwen3-4B-fast": (0.03, 0.09),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.05, 0.20),
    "meta-llama/Llama-3.3-70B-Instruct": (0.13, 0.40),
    "meta-llama/Meta-Llama-3.1-8B-Instruct": (0.02, 0.06),
    "deepseek-ai/DeepSeek-V3-0324": (0.50, 1.50),
}

GEMINI_PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}


def _load_overrides(env_var: str, table: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    raw = os.getenv(env_var)
    if not raw:
        return table
    try:
        parsed = json.loads(raw)
        merged = dict(table)
        merged.update({k: (float(v[0]), float(v[1])) for k, v in parsed.items()})
        return merged
    except (ValueError, TypeError, IndexError, KeyError) as exc:
        log.warning("ignoring malformed %s: %s", env_var, exc)
        return table


def cost_usd(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Cost of one call, or None when the model has no published price in the table."""
    table = (
        _load_overrides("NEBIUS_PRICES", NEBIUS_PRICES)
        if provider == "nebius"
        else _load_overrides("GEMINI_PRICES", GEMINI_PRICES)
    )
    price = table.get(model)
    if price is None:
        return None
    return (prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000
