"""One live smoke test against the public demo collection. Runs only with ``XTAL_LIVE=1``;
every call carries ``is_demo: true``."""

from __future__ import annotations

import os

import pytest
from shopping_agent import SearchFilters, ShoppingSessionContext
from xtal_commerce_backend import SearchRequest, XtalStorefrontBackend

pytestmark = pytest.mark.live

BASE_URL = os.environ.get("XTAL_BASE_URL", "https://www.xtalsearch.com")
COLLECTION = "flag-and-anthem"
QUERIES = ("warm shirt for a fall bonfire", "hoodie", "navy quarter zip pullover")


@pytest.fixture
def live_backend():
    if os.environ.get("XTAL_LIVE") != "1":
        pytest.skip("set XTAL_LIVE=1 to call the XTAL API")
    return XtalStorefrontBackend(BASE_URL, COLLECTION, is_demo=True)


@pytest.fixture
def session() -> ShoppingSessionContext:
    return ShoppingSessionContext(session_id="live-smoke", user_id="smoke")


async def test_three_searches_return_ranked_non_empty_results(live_backend, session):
    assert live_backend.client.is_demo is True
    for query in QUERIES:
        products = await live_backend.search_products(session, query, limit=8)
        assert products, query
        ids = [p.product_id for p in products]
        assert len(ids) == len(set(ids)), query
        assert all(p.title and p.price > 0 and p.attributes for p in products), query
        # Ranked: XTAL's own relevance score is highest on the first row it returned.
        response = await live_backend.client.search(SearchRequest(query=query, limit=8))
        scores = response.relevance_scores
        first = str(response.results[0]["id"])
        assert scores.get(first) == max(scores.values()), query


async def test_a_max_price_filter_is_honored(live_backend, session):
    ceiling = 40.0
    products = await live_backend.search_products(
        session, "hoodie", SearchFilters(max_price=ceiling), limit=8
    )
    assert products
    assert all(p.price <= ceiling for p in products), [p.price for p in products]
