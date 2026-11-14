"""Live System One selector smoke test.

Run with a local laya model (downloads/caches once):

    CLIVER_AGENT_SYSTEM_ONE_PROVIDER=local \
    uv run --extra local-system-one python scripts/system_one_smoke.py

Or against a remote endpoint by setting the provider-specific variables from
`.env.example`. The script only exercises the selector; it never calls the
main chat model.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys

from cliver_core import tool

from app.agents.core import build_system_one_selector, close_system_one_providers
from app.settings import Settings


@tool(description="List products in the catalogue.", safety="safe")
def products_list() -> list[dict]:
    return [{"text": "products"}]


@tool(description="Read the signed-in user's profile.", safety="safe")
def profile_read() -> list[dict]:
    return [{"text": "profile"}]


@tool(description="Refund a customer order.", safety="mutating")
def refund_order(order_id: int) -> list[dict]:
    return [{"text": f"refunded {order_id}"}]


@tool(description="Translate text into another language.", safety="safe")
def translate_text(text: str, language: str) -> list[dict]:
    return [{"text": f"{text} -> {language}"}]


TOOLS = [products_list, profile_read, refund_order, translate_text]


async def main() -> int:
    # Keep the smoke test meaningful for a tiny synthetic catalogue.
    settings = Settings(
        agent_system_one_min_tools=2,
        agent_system_one_top_k_tools=2,
    )
    if (
        settings.agent_system_one_provider.strip().lower() == "local"
        and importlib.util.find_spec("laya") is None
    ):
        print(
            "The local System One provider needs laya. Run "
            "`uv sync --extra local-system-one` first.",
            file=sys.stderr,
        )
        return 2
    selector = build_system_one_selector(settings)
    if selector is None:
        print(
            "System One selector is disabled. Set "
            "CLIVER_AGENT_SYSTEM_ONE_PROVIDER=local (or bailian/typesafe/http) "
            "and install the matching dependency.",
            file=sys.stderr,
        )
        return 2

    try:
        selected = await selector.select_tools(TOOLS, "I need a refund for order 42")
    finally:
        await close_system_one_providers()

    names = [item.name for item in selected]
    print(f"selected tools: {names}")
    if not names:
        print("selector returned an empty catalogue", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
