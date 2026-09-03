"""An XTAL Search backend for Anthropic's commerce agents.

``XtalStorefrontBackend`` implements ``shopping_agent.StorefrontBackend``: the catalog
methods call XTAL's search endpoint through ``XtalClient`` and the rows are mapped by
``mapper``; every other method is delegated to an optional host object or answers with the
blueprint's own "not offered" signal.
"""

from .backend import HostServices, XtalStorefrontBackend
from .client import SearchRequest, SearchResponse, XtalClient, XtalError
from .mapper import (
    apply_sort,
    build_search_request,
    fallback_request,
    map_product,
    map_product_details,
    within_price_band,
)

__all__ = [
    "HostServices",
    "SearchRequest",
    "SearchResponse",
    "XtalClient",
    "XtalError",
    "XtalStorefrontBackend",
    "apply_sort",
    "build_search_request",
    "fallback_request",
    "map_product",
    "map_product_details",
    "within_price_band",
]
