"""SearchFilters to an XTAL request: category, price band, attributes, sort, and
pagination with search_context, at the request level and through the backend."""

from __future__ import annotations

from shopping_agent import SearchFilters
from xtal_commerce_backend import (
    SearchRequest,
    apply_sort,
    build_search_request,
    fallback_request,
    map_product,
    within_price_band,
)


def test_a_bare_query_sends_only_the_required_fields():
    body = build_search_request("flannel shirt", None, 8).body("flag-and-anthem", True)
    assert body == {
        "query": "flannel shirt",
        "collection": "flag-and-anthem",
        "limit": 8,
        "search_source": "commerce-agent",
        "is_demo": True,
    }


def test_category_becomes_a_facet_filter_on_the_configured_prefix():
    filters = SearchFilters(category="Long Sleeve Shirts")
    request = build_search_request("shirt", filters, 6)
    assert request.facet_filters == {"category": ["long-sleeve-shirts"]}
    request = build_search_request("shirt", filters, 6, category_facet="product-type")
    assert request.facet_filters == {"product-type": ["long-sleeve-shirts"]}


def test_price_band_becomes_price_range_with_only_the_bounds_set():
    request = build_search_request("shirt", SearchFilters(max_price=80), 8)
    assert request.body("c", True)["price_range"] == {"max": 80}
    request = build_search_request("shirt", SearchFilters(min_price=20, max_price=80), 8)
    assert request.body("c", True)["price_range"] == {"min": 20, "max": 80}
    assert "price_range" not in build_search_request("shirt", SearchFilters(), 8).body("c", True)


def test_attributes_become_facet_filters_by_tag_prefix():
    filters = SearchFilters(attributes={"color": "Navy", "Material": "stretch knit"})
    request = build_search_request("shirt", filters, 8)
    assert request.facet_filters == {"color": ["navy"], "material": ["stretch-knit"]}


def test_sort_passes_through_and_relevance_is_omitted():
    assert build_search_request("s", SearchFilters(sort="price_asc"), 8).sort_by == "price_asc"
    assert build_search_request("s", SearchFilters(sort="relevance"), 8).sort_by is None
    assert "sort_by" not in build_search_request("s", None, 8).body("c", True)


def test_is_demo_and_api_key_follow_the_client(client, transport):
    import asyncio

    asyncio.run(client.search(SearchRequest(query="shirt")))
    assert transport.requests[-1]["is_demo"] is True
    assert "X-API-Key" not in transport.headers[-1]


def test_pagination_sends_offset_and_the_previous_search_context():
    context = {"augmented_query": "men's flannel shirt", "product_keyword": "shirt"}
    request = build_search_request("shirt", None, 8, offset=8, search_context=context)
    body = request.body("flag-and-anthem", True)
    assert body["offset"] == 8
    assert body["search_context"] == context
    first_page = build_search_request("shirt", None, 8).body("flag-and-anthem", True)
    assert "offset" not in first_page and "search_context" not in first_page


async def test_the_backend_passes_the_context_back_on_the_same_query(backend, transport, session):
    await backend.search_products(session, "warm shirt for a fall bonfire")
    assert "search_context" not in transport.requests[0]
    await backend.search_products(
        session, "Warm shirt for a fall  bonfire", SearchFilters(max_price=90)
    )
    second = transport.requests[1]
    assert second["search_context"]["product_keyword"] == "shirt"
    assert second["price_range"] == {"max": 90}
    # A different query starts fresh.
    await backend.search_products(session, "hoodie")
    assert "search_context" not in transport.requests[2]


def test_fallback_drops_facets_and_folds_the_category_into_the_query():
    filters = SearchFilters(category="shirts", attributes={"stretch": "yes"}, max_price=80)
    request = build_search_request("warm layer", filters, 8)
    assert request.facet_filters == {"category": ["shirts"], "stretch": ["yes"]}
    retry = fallback_request(request, filters)
    assert retry is not None
    assert retry.facet_filters == {}
    assert retry.query == "shirts warm layer"
    assert retry.price_max == 80 and retry.limit == 8
    assert fallback_request(build_search_request("warm layer", None, 8), None) is None


def test_the_price_band_is_checked_on_the_rows(recorded):
    product = map_product(recorded["results"][0])
    assert product.price == 69.5
    assert within_price_band(product, None)
    assert within_price_band(product, SearchFilters(max_price=80))
    assert not within_price_band(product, SearchFilters(max_price=60))
    assert not within_price_band(product, SearchFilters(min_price=70))
    assert within_price_band(product, SearchFilters(min_price=69.5, max_price=69.5))


def test_price_sorts_reorder_the_page_and_relevance_keeps_it(edge_cases, recorded):
    products = [map_product(row) for row in edge_cases["results"][:2]]
    assert [p.price for p in products] == [69.0, 18.5]
    assert [p.price for p in apply_sort(products, "price_asc")] == [18.5, 69.0]
    assert [p.price for p in apply_sort(products, "price_desc")] == [69.0, 18.5]
    assert apply_sort(products, "relevance") == products
    assert apply_sort(products, "rating") == products
