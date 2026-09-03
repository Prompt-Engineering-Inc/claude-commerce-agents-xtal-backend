"""Fixtures over the recorded XTAL response and an httpx mock transport that records
what the client sent."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from shopping_agent import ShoppingSessionContext
from xtal_commerce_backend import XtalClient, XtalStorefrontBackend

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED = FIXTURES / "xtal_search_flag_and_anthem.json"
EDGE_CASES = FIXTURES / "xtal_edge_cases.json"
BASE_URL = "https://xtal.test"
COLLECTION = "flag-and-anthem"


def load_fixture(path: Path = RECORDED) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class RecordingTransport(httpx.AsyncBaseTransport):
    """Answers every POST with ``responder(body)`` and keeps the bodies it saw."""

    def __init__(self, responder: Callable[[dict[str, Any]], httpx.Response]) -> None:
        self.responder = responder
        self.requests: list[dict[str, Any]] = []
        self.headers: list[httpx.Headers] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        self.requests.append(body)
        self.headers.append(request.headers)
        return self.responder(body)


def json_response(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


@pytest.fixture
def recorded() -> dict[str, Any]:
    return load_fixture()


@pytest.fixture
def edge_cases() -> dict[str, Any]:
    return load_fixture(EDGE_CASES)


@pytest.fixture
def transport(recorded) -> RecordingTransport:
    return RecordingTransport(lambda body: json_response(recorded))


@pytest.fixture
def client(transport) -> XtalClient:
    return XtalClient(BASE_URL, COLLECTION, transport=transport)


@pytest.fixture
def backend(client) -> XtalStorefrontBackend:
    return XtalStorefrontBackend(BASE_URL, COLLECTION, client=client)


@pytest.fixture
def session() -> ShoppingSessionContext:
    return ShoppingSessionContext(session_id="s-1", user_id="demo-user")
