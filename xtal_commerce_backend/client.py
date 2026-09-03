"""The HTTP client for XTAL's search endpoint: one request shape, one response shape, and
honest errors. ``POST {base_url}/api/xtal/search`` with a JSON body; paid collections send
``X-API-Key``. Every call carries ``is_demo`` as constructed, and one INFO line is logged
per call."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("xtal_commerce_backend")

SEARCH_PATH = "/api/xtal/search"
SEARCH_SOURCE = "commerce-agent"


class XtalError(Exception):
    """XTAL did not answer with a usable result: a 4xx or 5xx, a timeout, a connection
    failure, or a body that is not JSON. The message names the failure only, never the
    response body. The blueprint's executor reports any exception a catalog method raises
    as the tool being temporarily unavailable, so the model says so instead of guessing.
    The blueprint's ``Unavailable`` is not raised here: the executor words it for a cart
    write ("Nothing was added: ...")."""


@dataclass(frozen=True)
class SearchRequest:
    """One search as XTAL takes it. ``search_context`` is the object a previous response
    returned for the same query; pass it back when filtering or paginating that query."""

    query: str
    limit: int = 8
    offset: int = 0
    facet_filters: dict[str, list[str]] = field(default_factory=dict)
    price_min: float | None = None
    price_max: float | None = None
    sort_by: str | None = None
    search_context: dict[str, Any] | None = None
    session_id: str | None = None

    def body(self, collection: str, is_demo: bool) -> dict[str, Any]:
        """The JSON body. Absent fields are left out; ``price_range`` carries only the
        bounds that are set."""
        body: dict[str, Any] = {
            "query": self.query,
            "collection": collection,
            "limit": self.limit,
            "search_source": SEARCH_SOURCE,
            "is_demo": is_demo,
        }
        if self.offset:
            body["offset"] = self.offset
        if self.facet_filters:
            body["facet_filters"] = self.facet_filters
        price_range: dict[str, float] = {}
        if self.price_min is not None:
            price_range["min"] = self.price_min
        if self.price_max is not None:
            price_range["max"] = self.price_max
        if price_range:
            body["price_range"] = price_range
        if self.sort_by:
            body["sort_by"] = self.sort_by
        if self.search_context:
            body["search_context"] = self.search_context
        if self.session_id:
            body["session_id"] = self.session_id
        return body


@dataclass
class SearchResponse:
    """The fields this package reads from XTAL's response; ``raw`` is the whole body.
    ``query_time`` is passed through as XTAL returns it."""

    results: list[dict[str, Any]]
    total: int
    query_time: float | None
    search_context: dict[str, Any] | None
    computed_facets: dict[str, dict[str, int]]
    relevance_scores: dict[str, float]
    raw: dict[str, Any]

    @classmethod
    def parse(cls, data: Any) -> SearchResponse:
        if not isinstance(data, dict):
            raise XtalError("search returned a malformed response")
        results = data.get("results")
        if not isinstance(results, list):
            results = []
        query_time = data.get("query_time")
        context = data.get("search_context")
        return cls(
            results=[row for row in results if isinstance(row, dict)],
            total=int(data.get("total") or len(results)),
            query_time=float(query_time) if isinstance(query_time, int | float) else None,
            search_context=context if isinstance(context, dict) else None,
            computed_facets=data.get("computed_facets") or {},
            relevance_scores=data.get("relevance_scores") or {},
            raw=data,
        )


class XtalClient:
    """``transport`` is httpx's seam for tests (``httpx.MockTransport``)."""

    def __init__(
        self,
        base_url: str,
        collection: str,
        api_key: str | None = None,
        is_demo: bool = True,
        timeout: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not collection:
            raise ValueError("collection is required")
        self.base_url = base_url.rstrip("/")
        self.collection = collection
        self.is_demo = is_demo
        self.timeout = timeout
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        self._http = httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, headers=headers, transport=transport
        )

    async def search(self, request: SearchRequest) -> SearchResponse:
        body = request.body(self.collection, self.is_demo)
        started = time.monotonic()
        try:
            response = await self._http.post(SEARCH_PATH, json=body)
        except httpx.TimeoutException as error:
            raise XtalError(f"search timed out after {self.timeout:g}s") from error
        except httpx.HTTPError as error:
            raise XtalError("search could not be reached") from error
        if response.status_code >= 400:
            raise XtalError(f"search returned HTTP {response.status_code}")
        try:
            parsed = SearchResponse.parse(response.json())
        except ValueError as error:
            raise XtalError("search returned a malformed response") from error
        logger.info(
            "xtal search collection=%s query_chars=%d results=%d total=%d query_time=%s "
            "http_ms=%d is_demo=%s",
            self.collection,
            len(request.query),
            len(parsed.results),
            parsed.total,
            parsed.query_time,
            round((time.monotonic() - started) * 1000),
            self.is_demo,
        )
        return parsed

    async def aclose(self) -> None:
        await self._http.aclose()
