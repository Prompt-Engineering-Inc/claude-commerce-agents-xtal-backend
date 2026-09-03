"""``XtalStorefrontBackend``: the blueprint's ``StorefrontBackend`` over XTAL. The catalog
methods call the client and the mapper; everything else goes to the ``host`` object a
deployment passes, or answers as a system this store does not have."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Any, Protocol, runtime_checkable

from shopping_agent import (
    Cart,
    CheckoutHandoff,
    Disclosure,
    FulfillmentOption,
    NotOffered,
    Order,
    Policy,
    Product,
    ProductDetails,
    SearchFilters,
    ShoppingSessionContext,
    StorefrontBackend,
    UserPreferences,
)

from .client import SearchRequest, XtalClient
from .mapper import (
    DEFAULT_CATEGORY_FACET,
    apply_sort,
    build_search_request,
    fallback_request,
    map_product,
    map_product_details,
    product_id,
    within_price_band,
)

MAX_LIMIT = 48  # XTAL's own page size
DETAILS_LIMIT = 12
_RECORD_CACHE = 500
_CONTEXT_CACHE = 200


@runtime_checkable
class HostServices(Protocol):
    """What a deployment can supply beside the catalog. Every method is optional: the
    backend calls the ones the object has and answers the rest itself. Signatures match
    ``StorefrontBackend``."""

    async def get_cart(self, session: ShoppingSessionContext) -> Cart: ...

    async def add_to_cart(
        self, session: ShoppingSessionContext, product_id: str, quantity: int
    ) -> Cart: ...

    async def update_cart_item(
        self, session: ShoppingSessionContext, product_id: str, quantity: int
    ) -> Cart: ...

    async def remove_from_cart(self, session: ShoppingSessionContext, product_id: str) -> Cart: ...

    async def get_preferences(self, session: ShoppingSessionContext) -> UserPreferences: ...

    async def get_orders(self, session: ShoppingSessionContext, limit: int) -> list[Order]: ...

    async def get_order(self, session: ShoppingSessionContext, order_id: str) -> Order | None: ...

    async def search_policies(
        self, session: ShoppingSessionContext, query: str
    ) -> list[Policy]: ...

    async def get_fulfillment_options(
        self, session: ShoppingSessionContext, product_ids: list[str]
    ) -> list[FulfillmentOption]: ...

    async def checkout_handoff(
        self, session: ShoppingSessionContext, cart: Cart
    ) -> list[CheckoutHandoff]: ...

    async def get_account_context(
        self, session: ShoppingSessionContext
    ) -> dict[str, Any] | None: ...

    async def get_disclosure(
        self, session: ShoppingSessionContext, product_id: str
    ) -> Disclosure | None: ...

    def reset_session(self, session_id: str) -> None: ...


def session_tag(session_id: str | None) -> str:
    """A digest in place of the session id, which on the blueprint's hosts is also the
    request credential; XTAL's analytics get the tag."""
    return hashlib.sha256(session_id.encode()).hexdigest()[:16] if session_id else "-"


class XtalStorefrontBackend(StorefrontBackend):
    """``base_url`` is the XTAL site, ``collection`` the catalog. A paid collection needs
    ``api_key``. ``is_demo`` marks every call as test traffic; set it False only for
    production traffic on a collection you are billed for. ``category_facet`` is the tag
    prefix a ``SearchFilters.category`` filters on. ``client`` replaces the HTTP client,
    for tests."""

    def __init__(
        self,
        base_url: str,
        collection: str,
        api_key: str | None = None,
        is_demo: bool = True,
        timeout: float = 8.0,
        host: HostServices | Any | None = None,
        *,
        category_facet: str = DEFAULT_CATEGORY_FACET,
        client: XtalClient | None = None,
    ) -> None:
        self.client = client or XtalClient(
            base_url, collection, api_key=api_key, is_demo=is_demo, timeout=timeout
        )
        self.collection = self.client.collection
        self.host = host
        self.category_facet = category_facet
        # Raw rows by id, from every search this backend ran: the details resolver's
        # memory, since XTAL has no product-by-id route yet.
        self._records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # The search_context XTAL returned per (session, query), passed back when the
        # same query is searched again with other filters.
        self._contexts: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    # -- catalog ---------------------------------------------------------------------

    async def search_products(
        self,
        session: ShoppingSessionContext,
        query: str,
        filters: SearchFilters | None = None,
        limit: int = 8,
    ) -> list[Product]:
        limit = max(1, min(int(limit), MAX_LIMIT))
        tag = session_tag(session.session_id)
        key = (tag, " ".join(query.lower().split()))
        request = build_search_request(
            query,
            filters,
            limit,
            category_facet=self.category_facet,
            search_context=self._contexts.get(key),
            session_id=tag,
        )
        response = await self.client.search(request)
        if not response.results and (retry := fallback_request(request, filters)) is not None:
            response = await self.client.search(retry)
        if response.search_context:
            self._remember_context(key, response.search_context)
        self._remember_records(response.results)
        products = [p for p in (map_product(row) for row in response.results) if p is not None]
        products = [p for p in products if within_price_band(p, filters)]
        return apply_sort(products, filters.sort if filters else "relevance")[:limit]

    async def get_product_details(
        self, session: ShoppingSessionContext, product_id: str
    ) -> ProductDetails | None:
        record = await self._resolve(session, product_id)
        return map_product_details(record) if record is not None else None

    async def _resolve(
        self, session: ShoppingSessionContext, product_id: str
    ) -> dict[str, Any] | None:
        """The one place an id becomes a record, so it can swap to a product-by-id route
        when XTAL has one. Today: a search for the product's title and SKU (both from the
        row a previous search returned; the id itself when the row is unknown), matched
        on id, with the remembered row as the fallback when the search misses it."""
        family_id, _, _ = product_id.partition(":")
        known = self._records.get(family_id)
        if known is not None:
            title = known.get("title") or known.get("name") or ""
            skus = known.get("skus") or []
            sku = skus[0] if isinstance(skus, list) and skus else ""
            query = f"{title} {sku}".strip() or family_id
        else:
            query = family_id
        request = SearchRequest(
            query=query, limit=DETAILS_LIMIT, session_id=session_tag(session.session_id)
        )
        response = await self.client.search(request)
        self._remember_records(response.results)
        match = next((row for row in response.results if _id_of(row) == family_id), None)
        return match or known

    def _remember_records(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            if (pid := _id_of(row)) is not None:
                self._records[pid] = row
                self._records.move_to_end(pid)
        while len(self._records) > _RECORD_CACHE:
            self._records.popitem(last=False)

    def _remember_context(self, key: tuple[str, str], context: dict[str, Any]) -> None:
        self._contexts[key] = context
        self._contexts.move_to_end(key)
        while len(self._contexts) > _CONTEXT_CACHE:
            self._contexts.popitem(last=False)

    def remembered(self, product_id: str) -> dict[str, Any] | None:
        """The raw row a search returned for this id, if any."""
        return self._records.get(product_id)

    # -- everything else: the host's, or not this store's ----------------------------

    def _hosted(self, name: str) -> Any | None:
        method = getattr(self.host, name, None) if self.host is not None else None
        return method if callable(method) else None

    async def get_cart(self, session: ShoppingSessionContext) -> Cart:
        if method := self._hosted("get_cart"):
            return await method(session)
        return Cart()

    async def add_to_cart(
        self, session: ShoppingSessionContext, product_id: str, quantity: int
    ) -> Cart:
        if method := self._hosted("add_to_cart"):
            return await method(session, product_id, quantity)
        raise NotOffered("A cart")

    async def update_cart_item(
        self, session: ShoppingSessionContext, product_id: str, quantity: int
    ) -> Cart:
        if method := self._hosted("update_cart_item"):
            return await method(session, product_id, quantity)
        raise NotOffered("A cart")

    async def remove_from_cart(self, session: ShoppingSessionContext, product_id: str) -> Cart:
        if method := self._hosted("remove_from_cart"):
            return await method(session, product_id)
        raise NotOffered("A cart")

    async def get_preferences(self, session: ShoppingSessionContext) -> UserPreferences:
        if method := self._hosted("get_preferences"):
            return await method(session)
        return UserPreferences(user_id=session.user_id, display_name="Guest")

    async def get_orders(self, session: ShoppingSessionContext, limit: int = 5) -> list[Order]:
        if method := self._hosted("get_orders"):
            return await method(session, limit)
        return []

    async def get_order(self, session: ShoppingSessionContext, order_id: str) -> Order | None:
        if method := self._hosted("get_order"):
            return await method(session, order_id)
        return None

    async def search_policies(self, session: ShoppingSessionContext, query: str) -> list[Policy]:
        if method := self._hosted("search_policies"):
            return await method(session, query)
        return []

    async def get_fulfillment_options(
        self, session: ShoppingSessionContext, product_ids: list[str]
    ) -> list[FulfillmentOption]:
        if method := self._hosted("get_fulfillment_options"):
            return await method(session, product_ids)
        return []

    async def checkout_handoff(
        self, session: ShoppingSessionContext, cart: Cart
    ) -> list[CheckoutHandoff]:
        if method := self._hosted("checkout_handoff"):
            return await method(session, cart)
        return []

    async def get_account_context(self, session: ShoppingSessionContext) -> dict[str, Any] | None:
        if method := self._hosted("get_account_context"):
            return await method(session)
        return None

    async def get_disclosure(
        self, session: ShoppingSessionContext, product_id: str
    ) -> Disclosure | None:
        if method := self._hosted("get_disclosure"):
            return await method(session, product_id)
        return None

    def reset_session(self, session_id: str) -> None:
        """Per-session cleanup the blueprint's demo host calls; the host's, if it has one."""
        if method := self._hosted("reset_session"):
            method(session_id)

    async def aclose(self) -> None:
        await self.client.aclose()


def _id_of(row: dict[str, Any]) -> str | None:
    return product_id(row)
