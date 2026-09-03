"""The storefront half of the contract checks that upstream ties to the merchant portal,
plus what the XTAL host itself promises: no cart, order, or policy tool in the agent's
tool list, and product reads over what searches returned."""

from __future__ import annotations

from demo_common.tests.contract import STOREFRONT_PUBLIC, _dependency_of, _routes
from demo_common.tests.fixtures import start_shopper


def test_storefront_public_routes_are_exactly_the_blueprints(main, extra_public_routes):
    routes = _routes(main.app)
    assert not [r for r in routes if r.path.startswith("/api/merchant")]
    public = {r.path for r in routes if _dependency_of(r) is None}
    assert public == STOREFRONT_PUBLIC | extra_public_routes


def test_xtal_health_names_the_store_and_the_model(main, client):
    health = client.get("/api/health").json()
    assert health["store"] == "Flag & Anthem" == main.backend.store_name
    assert health["model"] == main.agent.config.model
    assert health["products"] == len(main.backend.products)
    assert set(health["skills"]) == {
        "memory-personalization",
        "purchase-research",
        "search-discovery",
    }


def test_xtal_memory_routes_carry_the_key_in_the_body(main):
    routes = [r for r in _routes(main.app) if r.path.endswith("/memory")]
    assert {(m, r.path) for r in routes for m in r.methods} == {
        ("GET", "/api/memory"),
        ("PATCH", "/api/memory"),
        ("DELETE", "/api/memory"),
    }
    assert not any(r.dependant.path_params or r.dependant.query_params for r in routes)


def test_the_agent_has_no_cart_order_policy_or_fulfillment_tools(main):
    names = {tool["name"] for tool in main.agent._tools}
    assert {"search_products", "get_product_details", "present_products"} <= names
    assert names.isdisjoint(main.agent.config.absent_tools())
    assert not names & {"add_to_cart", "get_cart", "checkout", "get_orders", "search_policies"}


def test_products_route_lists_what_searches_returned_and_ids_with_slashes_miss(main, client):
    weird = "gid://acme/Product/7"
    missing = client.get(f"/api/products/{weird}")
    assert missing.status_code == 404 and missing.json()["detail"] == "Product not found"
    assert client.post("/api/session", json={"user_id": "demo-user"}).json()["name"] == "Jordan"
    assert client.get("/api/cart", headers=start_shopper(client)).json()["items"] == []
