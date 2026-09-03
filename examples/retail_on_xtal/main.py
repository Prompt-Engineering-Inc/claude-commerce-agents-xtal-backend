"""Anthropic's ACME retail example API with the catalog served by XTAL.

    uvicorn retail_on_xtal.main:app --app-dir examples --port 8000

with ``vendor/commerce-agents/examples`` on the Python path as well (``scripts/run_demo.py``
does both). When ``XTAL_COLLECTION`` is set, the storefront routes, the shopping agent, and
its memory run over ``XtalDemoStorefront``; cart, orders, policies, and fulfillment are
switched off through the blueprint's ``enable_*`` config. When it is not set, this module
is the upstream retail app, unchanged. No upstream file is edited either way.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

EXAMPLE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLE_ROOT.parents[1]
DATA_DIR = EXAMPLE_ROOT / "data"

# This repo's .env, then the example's, then the vendored repo root's (load_demo_env).
load_dotenv(REPO_ROOT / ".env", override=False)

XTAL_SEARCH_NOTES = (
    "This catalog's search understands plain language, so word the query as a shopper "
    "would and let the results carry the ranking. Put a color, material, pattern, fit, "
    "size, style, season, or occasion the customer stated in filters.attributes under "
    'that name (for example {"color": "navy"}); a stated price ceiling goes in max_price.'
)


@dataclass
class Demo:
    app: Any
    host: Any
    backend: Any
    agent: Any
    DATA_DIR: Path


def brand_name(collection: str) -> str:
    return os.environ.get("XTAL_BRAND_NAME") or collection.replace("-", " ").title()


def build_demo(backend: Any | None = None) -> Demo:
    """The XTAL-backed host. ``backend`` replaces the live one (tests pass a mock)."""
    from commerce_common.memory import JsonFileMemoryStore
    from commerce_common.skills import SkillRegistry
    from demo_common import REPO_ROOT as UPSTREAM_ROOT
    from demo_common import MemorySeeder, build_storefront_host, load_demo_env
    from shopping_agent import ShoppingAgentConfig
    from shopping_agent_runtime import ShoppingAgent

    from .storefront import DemoProfiles, XtalDemoStorefront

    load_demo_env(EXAMPLE_ROOT)
    collection = os.environ["XTAL_COLLECTION"]
    brand = brand_name(collection)
    if backend is None:
        backend = XtalDemoStorefront(
            os.environ.get("XTAL_BASE_URL", "https://www.xtalsearch.com"),
            collection,
            api_key=os.environ.get("XTAL_API_KEY") or None,
            is_demo=os.environ.get("XTAL_IS_DEMO", "1") != "0",
            host=DemoProfiles(DATA_DIR),
            category_facet=os.environ.get("XTAL_CATEGORY_FACET", "category"),
            store_name=brand,
        )
    config = ShoppingAgentConfig(
        brand_name=brand,
        assistant_name=f"{brand} Assistant",
        brand_voice="professional, warm, and brief",
        domain_search_notes=XTAL_SEARCH_NOTES,
        enable_cart=False,
        enable_orders=False,
        enable_policies=False,
        enable_fulfillment=False,
    )
    # The flows that need a cart or order history are left out of the skill index.
    skills = SkillRegistry.from_dir(UPSTREAM_ROOT / "shopping-agent" / "skills")
    kept = SkillRegistry(
        [
            skill
            for skill in skills._skills  # noqa: SLF001 - the registry exposes no filter
            if skill.name in {"search-discovery", "purchase-research", "memory-personalization"}
        ]
    )
    agent = ShoppingAgent(
        backend=backend,
        skills=kept,
        config=config,
        memory_store=JsonFileMemoryStore(DATA_DIR / ".memory-store.json"),
    )
    host = build_storefront_host(
        title=f"{brand} on XTAL demo API",
        example_root=EXAMPLE_ROOT,
        backend=backend,
        agent=agent,
        memory_seeder=MemorySeeder(
            DATA_DIR / "memory-seed.json", marker=DATA_DIR / ".memory-seeded.json"
        ),
    )
    return Demo(app=host.app, host=host, backend=backend, agent=agent, DATA_DIR=DATA_DIR)


if os.environ.get("XTAL_COLLECTION"):
    demo = build_demo()
    app, host, backend, agent = demo.app, demo.host, demo.backend, demo.agent
else:
    from retail.api import main as _upstream

    app, host, backend, agent = (
        _upstream.app,
        _upstream.host,
        _upstream.backend,
        _upstream.agent,
    )
    DATA_DIR = _upstream.DATA_DIR
