"""The upstream contract suite over ``retail_on_xtal``: the fixtures its ``fixtures.py``
asks a vertical to define, a mock XTAL transport by default (a live client with
``XTAL_LIVE=1``), and skips, by name and with a reason, for the tests of systems this
backend switches off or does not have (cart, orders, the merchant portal, a catalog file)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("XTAL_COLLECTION", "flag-and-anthem")
os.environ.setdefault("XTAL_BRAND_NAME", "Flag & Anthem")

from demo_common.tests.fixtures import *  # noqa: E402, F403
from xtal_commerce_backend import XtalClient, map_product  # noqa: E402

from retail_on_xtal import main as main_module  # noqa: E402
from retail_on_xtal.storefront import DemoProfiles, XtalDemoStorefront  # noqa: E402

from ..conftest import (  # noqa: E402
    BASE_URL,
    COLLECTION,
    RecordingTransport,
    json_response,
    load_fixture,
)

LIVE = os.environ.get("XTAL_LIVE") == "1"
RECORDED = load_fixture()

SKIPS = {
    # The merchant agent and portal are out of scope for this backend.
    "test_public_route_sets_are_closed_and_each_role_has_its_own_token_store": "no merchant portal",
    "test_merchant_session_binds_the_server_held_identity": "no merchant portal",
    "test_health_names_the_store_and_the_model": "no merchant portal (see test_host.py)",
    "test_memory_routes_carry_the_key_in_the_body": "no merchant portal (see test_host.py)",
    "test_merchant_memory_lists_deletes_one_fact_and_purges": "no merchant portal",
    "test_listings_total_counts_the_universe_and_survives_paging": "no merchant portal",
    "test_ids_containing_slashes_reach_the_id_routes": "no merchant portal (see test_host.py)",
    "test_overview_and_alerts_carry_the_portal_keys": "no merchant portal",
    "test_preview_card_buttons_report_a_hold_apart_from_an_apply": "no merchant portal",
    "test_portal_config_follows_the_host_approval_switch": "no merchant portal",
    "test_snapshot_periods_end_before_boot_and_compare_to_the_prior_block": "no merchant portal",
    "test_campaigns_and_issues_land_in_the_same_week_as_the_snapshot": "no merchant portal",
    "test_listing_ids_resolve_case_insensitively_and_browse_queries_return_the_universe": "no merchant portal",
    "test_pricing_context_repeats_the_deployments_movement_caps": "no merchant portal",
    "test_every_staging_path_is_the_agents_proposal_and_applying_is_the_operators_act": "no merchant portal",
    "test_unknown_ids_are_refused_on_every_staging_path": "no merchant portal",
    "test_campaign_previews_carry_budget_audience_and_copy": "no merchant portal",
    "test_two_staged_restocks_both_count_when_applied": "no merchant portal",
    # Systems switched off through enable_* in this deployment.
    "test_orders_route_lists_the_callers_own_orders_newest_first": "orders switched off",
    "test_orders_are_newest_first_per_user_and_resolve_case_insensitively": "orders switched off",
    "test_cart_lines_belong_to_the_session": "cart switched off",
    # The catalog is XTAL, not a catalog.json beside a showcase file.
    "test_showcase_products_are_catalog_records_plus_the_backends_stamps": "catalog is served by XTAL",
}
if LIVE:
    SKIPS["test_a_non_relevance_sort_keeps_only_relevant_matches"] = (
        "the hero id is fixed by the recorded fixture, not by live ranking"
    )


def pytest_collection_modifyitems(items):
    for item in items:
        if (reason := SKIPS.get(item.originalname or item.name)) is not None:
            item.add_marker(pytest.mark.skip(reason=reason))


def _make_storefront() -> XtalDemoStorefront:
    if LIVE:
        client = XtalClient("https://www.xtalsearch.com", COLLECTION, is_demo=True)
    else:
        transport = RecordingTransport(lambda body: json_response(RECORDED))
        client = XtalClient(BASE_URL, COLLECTION, transport=transport)
    return XtalDemoStorefront(
        BASE_URL,
        COLLECTION,
        host=DemoProfiles(main_module.DATA_DIR),
        client=client,
        store_name="Flag & Anthem",
    )


@pytest.fixture(scope="session")
def main():
    return main_module.build_demo(backend=_make_storefront())


@pytest.fixture(scope="session")
def make_storefront():
    return _make_storefront


@pytest.fixture(scope="session")
def extra_public_routes() -> set[str]:
    return set()


@pytest.fixture
def merchant():
    pytest.skip("no merchant portal")


@pytest.fixture(scope="session")
def merchant_identity():
    return None


@pytest.fixture(scope="session")
def make_merchant_router():
    return None


@pytest.fixture
def merchant_extensions() -> list:
    return []


@pytest.fixture(scope="session")
def restockable_listing() -> None:
    return None


@pytest.fixture(scope="session")
def cart_product() -> str:
    return str(RECORDED["results"][0]["id"])


@pytest.fixture(scope="session")
def relevance_probe() -> tuple[str, str, str, set[str]]:
    """(query, non-relevance sort, product that must lead, faint matches that must be
    cut). Over the recorded fixture a price sort is stable, so the first row at the
    lowest price leads; the faint ids are ones the fixture does not carry."""
    products = [map_product(row) for row in RECORDED["results"]]
    lowest = min(p.price for p in products)
    hero = next(p.product_id for p in products if p.price == lowest)
    return ("warm shirt for a fall bonfire", "price_asc", hero, {"ZZ-NOPE", "AR-0000"})
