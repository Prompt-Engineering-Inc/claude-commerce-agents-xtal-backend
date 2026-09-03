"""What the blueprint's shared demo routes need beyond ``StorefrontBackend`` (the
``DemoStorefront`` protocol in ``demo_common.host``): a store name, the products the
routes can list, a synchronous lookup by id, per-session cleanup, and an order feed. Here
the catalog is XTAL, so the listing is what searches have returned so far."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from demo_common.storefront_fixtures import load_users, preferences_of
from shopping_agent import Order, ProductDetails, ShoppingSessionContext, UserPreferences
from xtal_commerce_backend import XtalStorefrontBackend, map_product_details


class DemoProfiles:
    """The host object: demo shopper profiles from ``data/users.json``, as the ACME example
    keeps them. No cart, orders, or policies; those systems are switched off in the config."""

    def __init__(self, data_dir: Path) -> None:
        self._users: Mapping[str, UserPreferences] = load_users(data_dir)

    async def get_preferences(self, session: ShoppingSessionContext) -> UserPreferences:
        return preferences_of(self._users, session.user_id)


class XtalDemoStorefront(XtalStorefrontBackend):
    def __init__(self, *args, store_name: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.store_name = store_name

    @property
    def products(self) -> dict[str, ProductDetails]:
        """Every product a search has returned this process, by id."""
        listing: dict[str, ProductDetails] = {}
        for product_id, row in list(self._records.items()):
            if (details := map_product_details(row)) is not None:
                listing[product_id] = details
        return listing

    def product(self, product_id: str) -> ProductDetails | None:
        family_id, _, _ = product_id.partition(":")
        row = self.remembered(family_id)
        return map_product_details(row) if row is not None else None

    def recent_orders(self, limit: int = 6) -> list[Order]:
        del limit
        return []
