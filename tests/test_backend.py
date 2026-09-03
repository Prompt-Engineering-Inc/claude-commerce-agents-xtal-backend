"""The backend over a mock transport: errors, logging, the details resolver, the price
band, the empty-result fallback, and delegation to a host."""

from __future__ import annotations

import logging

import httpx
import pytest
from shopping_agent import (
    Cart,
    CartItem,
    NotOffered,
    Product,
    SearchFilters,
    ShoppingSessionContext,
    UserPreferences,
)
from xtal_commerce_backend import XtalClient, XtalError, XtalStorefrontBackend
from xtal_commerce_backend.backend import session_tag

from .conftest import BASE_URL, COLLECTION, RecordingTransport, json_response


def make_backend(responder, **kwargs) -> tuple[XtalStorefrontBackend, RecordingTransport]:
    transport = RecordingTransport(responder)
    client = XtalClient(BASE_URL, COLLECTION, transport=transport, **kwargs)
    return XtalStorefrontBackend(BASE_URL, COLLECTION, client=client), transport


# -- search --------------------------------------------------------------------------


async def test_search_returns_ranked_products_in_xtal_order(backend, session, recorded):
    products = await backend.search_products(session, "warm shirt for a fall bonfire", limit=8)
    assert [p.product_id for p in products] == [str(r["id"]) for r in recorded["results"][:8]]
    assert all(isinstance(p, Product) for p in products)


async def test_limit_is_clamped_and_sent(backend, transport, session):
    await backend.search_products(session, "shirt", limit=500)
    assert transport.requests[-1]["limit"] == 48
    await backend.search_products(session, "shirt", limit=0)
    assert transport.requests[-1]["limit"] == 1


async def test_the_session_id_reaches_xtal_only_as_a_digest(backend, transport, session):
    await backend.search_products(session, "shirt")
    sent = transport.requests[-1]["session_id"]
    assert sent == session_tag("s-1") and "s-1" not in sent and len(sent) == 16


async def test_rows_over_the_price_ceiling_are_dropped(backend, session):
    # Every recorded row is 69.50; XTAL applied no price cut, so the mapper must.
    assert await backend.search_products(session, "shirt", SearchFilters(max_price=60)) == []
    kept = await backend.search_products(session, "shirt", SearchFilters(max_price=70))
    assert kept and all(p.price <= 70 for p in kept)


async def test_an_empty_filtered_result_retries_without_facets(recorded, session):
    def responder(body):
        return json_response(
            recorded if "facet_filters" not in body else {"results": [], "total": 0}
        )

    backend, transport = make_backend(responder)
    filters = SearchFilters(category="Shirts", attributes={"color": "navy"})
    products = await backend.search_products(session, "warm layer", filters)
    assert products
    first, second = transport.requests
    assert first["facet_filters"] == {"category": ["shirts"], "color": ["navy"]}
    assert "facet_filters" not in second and second["query"] == "Shirts warm layer"


async def test_no_retry_when_the_unfiltered_search_is_empty(session):
    backend, transport = make_backend(lambda body: json_response({"results": [], "total": 0}))
    assert await backend.search_products(session, "nothing") == []
    assert len(transport.requests) == 1


async def test_one_info_line_per_call(backend, session, caplog):
    with caplog.at_level(logging.INFO, logger="xtal_commerce_backend"):
        await backend.search_products(session, "shirt")
    lines = [r.getMessage() for r in caplog.records if r.name == "xtal_commerce_backend"]
    assert len(lines) == 1
    line = lines[0]
    assert "collection=flag-and-anthem" in line
    assert "query_chars=5" in line
    assert "results=12" in line
    assert "query_time=1.300973653793335" in line
    assert "is_demo=True" in line


# -- errors --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 502, 503])
async def test_http_errors_raise_xtal_error_without_the_body(status, session):
    backend, _ = make_backend(lambda body: httpx.Response(status, json={"error": "secret detail"}))
    with pytest.raises(XtalError) as raised:
        await backend.search_products(session, "shirt")
    assert str(raised.value) == f"search returned HTTP {status}"
    assert "secret" not in str(raised.value)


async def test_a_timeout_raises_xtal_error(session):
    def responder(body):
        raise httpx.ReadTimeout("slow")

    backend, _ = make_backend(responder, timeout=8.0)
    with pytest.raises(XtalError, match="timed out after 8s"):
        await backend.search_products(session, "shirt")


async def test_a_connection_failure_and_a_malformed_body_raise_xtal_error(session):
    def down(body):
        raise httpx.ConnectError("refused")

    backend, _ = make_backend(down)
    with pytest.raises(XtalError, match="could not be reached"):
        await backend.search_products(session, "shirt")
    backend, _ = make_backend(lambda body: httpx.Response(200, content=b"<html>not json"))
    with pytest.raises(XtalError, match="malformed"):
        await backend.search_products(session, "shirt")
    backend, _ = make_backend(lambda body: httpx.Response(200, json=[1, 2, 3]))
    with pytest.raises(XtalError, match="malformed"):
        await backend.search_products(session, "shirt")


def test_the_executor_reports_an_xtal_error_as_the_tool_being_unavailable():
    """The reason XtalError is not the blueprint's Unavailable: the executor words that
    one for a cart write."""
    from shopping_agent import Unavailable
    from shopping_agent.executor import ShoppingToolExecutor

    assert not issubclass(XtalError, Unavailable)
    assert "Nothing was added" in ShoppingToolExecutor.sold_out_text
    assert "temporarily unavailable" in ShoppingToolExecutor.unavailable_text


# -- details -------------------------------------------------------------------------


async def test_details_search_the_title_and_sku_and_match_on_id(backend, transport, session):
    await backend.search_products(session, "warm shirt")
    details = await backend.get_product_details(session, "7793851662415")
    assert details is not None and details.product_id == "7793851662415"
    lookup = transport.requests[-1]
    assert lookup["query"] == "HERO STRETCH FLANNEL SHIRT M-FA24WS2174"
    assert lookup["limit"] == 12
    assert details.long_description and details.specs


async def test_an_unknown_id_is_searched_as_itself(backend, transport, session):
    assert await backend.get_product_details(session, "no-such-id") is None
    assert transport.requests[-1]["query"] == "no-such-id"


async def test_the_remembered_row_stands_in_when_the_lookup_misses(recorded, session):
    calls = {"n": 0}

    def responder(body):
        calls["n"] += 1
        return json_response(recorded if calls["n"] == 1 else {"results": [], "total": 0})

    backend, _ = make_backend(responder)
    await backend.search_products(session, "warm shirt")
    details = await backend.get_product_details(session, "7081381101647")
    assert details is not None and details.product_id == "7081381101647"


async def test_a_variant_id_resolves_through_its_family(edge_cases, session):
    backend, transport = make_backend(lambda body: json_response(edge_cases))
    await backend.search_products(session, "merino crew")
    details = await backend.get_product_details(session, "990001:RMC-L-OAT")
    assert details is not None and details.product_id == "990001"
    assert transport.requests[-1]["query"] == "Ridge Merino Crew"
    assert [v.product_id for v in details.variants][2] == "990001:RMC-L-OAT"


# -- everything that is not the catalog ------------------------------------------------


async def test_without_a_host_the_other_systems_answer_as_absent(backend, session):
    assert (await backend.get_cart(session)) == Cart()
    for call in (
        backend.add_to_cart(session, "x", 1),
        backend.update_cart_item(session, "x", 1),
        backend.remove_from_cart(session, "x"),
    ):
        with pytest.raises(NotOffered):
            await call
    guest = await backend.get_preferences(session)
    assert guest == UserPreferences(user_id="demo-user", display_name="Guest")
    assert await backend.get_orders(session) == []
    assert await backend.get_order(session, "o-1") is None
    assert await backend.search_policies(session, "returns") == []
    assert await backend.get_fulfillment_options(session, ["x"]) == []
    assert await backend.checkout_handoff(session, Cart()) == []
    assert await backend.get_account_context(session) is None
    assert await backend.get_disclosure(session, "x") is None
    backend.reset_session("s-1")  # no host: nothing to do, no error


class FakeHost:
    def __init__(self) -> None:
        self.reset_calls: list[str] = []
        self.cart = Cart(items=[CartItem(product_id="p", title="P", price=2.0, quantity=1)])

    async def get_cart(self, session: ShoppingSessionContext) -> Cart:
        return self.cart

    async def add_to_cart(self, session, product_id, quantity) -> Cart:
        return self.cart

    async def get_preferences(self, session) -> UserPreferences:
        return UserPreferences(user_id=session.user_id, display_name="Sam", loyalty_tier="gold")

    def reset_session(self, session_id: str) -> None:
        self.reset_calls.append(session_id)


async def test_a_host_supplies_what_it_has_and_the_rest_stays_absent(client, session):
    host = FakeHost()
    backend = XtalStorefrontBackend(BASE_URL, COLLECTION, host=host, client=client)
    assert (await backend.get_cart(session)).item_count == 1
    assert (await backend.add_to_cart(session, "p", 1)).item_count == 1
    assert (await backend.get_preferences(session)).display_name == "Sam"
    with pytest.raises(NotOffered):
        await backend.remove_from_cart(session, "p")
    assert await backend.get_orders(session) == []
    backend.reset_session("s-1")
    assert host.reset_calls == ["s-1"]


def test_the_client_needs_a_collection_and_sends_the_key_when_given():
    with pytest.raises(ValueError):
        XtalClient(BASE_URL, "")
    transport = RecordingTransport(lambda body: json_response({"results": []}))
    client = XtalClient(BASE_URL, COLLECTION, api_key="xtal_" + "a" * 48, transport=transport)
    import asyncio

    from xtal_commerce_backend import SearchRequest

    asyncio.run(client.search(SearchRequest(query="x")))
    assert transport.headers[-1]["X-API-Key"] == "xtal_" + "a" * 48
