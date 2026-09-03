# claude-commerce-agents-xtal-backend

An [XTAL Search](https://www.xtalsearch.com) backend for Anthropic's open-source
[commerce agents](https://github.com/anthropics/commerce-agents) blueprint.

Anthropic's shopping agent calls a `StorefrontBackend`. Their own guidance says the agent's
`search_products` tool should call the retailer's existing search and ranking, so "the
results should arrive already ranked" ([the deep-dive](https://claude.com/blog/the-anatomy-of-effective-commerce-agents)).
This package is that backend for any catalog indexed by XTAL: natural-language product
search with per-merchant brand and merchandising prompts, returned in the blueprint's
`Product` shape. Anthropic's ACME retail example runs over it unchanged, with one
environment variable.

## Run the retail example over XTAL

Python 3.11+ and Node 22+. Nothing here needs a paid XTAL collection: the public demo
collection `flag-and-anthem` answers without a key, and every call this repo makes is marked
`is_demo: true`.

```bash
git clone https://github.com/Prompt-Engineering-Inc/claude-commerce-agents-xtal-backend.git
cd claude-commerce-agents-xtal-backend

# 1. The blueprint, at the commit this package is pinned to (.upstream-pin.txt)
git clone https://github.com/anthropics/commerce-agents vendor/commerce-agents
git -C vendor/commerce-agents checkout fd4d59224ab96b43c6dc6888207c67b3bd5a24cf

# 2. Python: the blueprint's pinned packages, then this one
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
(cd vendor/commerce-agents && pip install -r requirements-dev.txt)
pip install --no-deps -e .

# 3. The storefront web app (upstream's, unchanged)
(cd vendor/commerce-agents/examples && npm ci)

# 4. Settings: XTAL_COLLECTION picks the catalog; ANTHROPIC_API_KEY runs the agent
cp .env.example .env                                     # then add ANTHROPIC_API_KEY

# 5. Run
python scripts/run_demo.py                               # API :8000, storefront :3000
```

Open http://localhost:3000. The storefront is Anthropic's ACME retail app; the assistant is
named after the collection (`XTAL_BRAND_NAME`), and every search it runs is an XTAL search
over that catalog. Try:

1. I need a warm shirt for a fall bonfire, under $80
2. Compare the top two
3. Which one has stretch?

[`docs/demo/RUN.md`](docs/demo/RUN.md) is one recorded run of those three turns: the
queries and filters the agent chose, XTAL's `query_time` per call, and time to first token
per turn, with screenshots.

The API alone: `python scripts/run_demo.py --api-only`, or

```bash
PYTHONPATH=examples:vendor/commerce-agents/examples uvicorn retail_on_xtal.main:app --app-dir examples --port 8000
```

On macOS and Linux, upstream's own runner starts the web app against a running API:
`python vendor/commerce-agents/scripts/run_demo.py retail --web-only --api-port 8000`. On
Windows that script execs a shell script and fails, so `scripts/run_demo.py` here starts
`next dev` itself.

## What is where

| Path | Contents |
|---|---|
| `xtal_commerce_backend/client.py` | `XtalClient`: `POST /api/xtal/search`, the request body, the response fields read, errors, one log line per call |
| `xtal_commerce_backend/mapper.py` | XTAL rows to `Product` and `ProductDetails`; `SearchFilters` to an XTAL request |
| `xtal_commerce_backend/backend.py` | `XtalStorefrontBackend`: the two catalog methods over the client and the mapper; everything else to an optional `host` |
| `examples/retail_on_xtal/` | Anthropic's retail example API with this backend swapped in when `XTAL_COLLECTION` is set; upstream's app otherwise |
| `tests/` | Mapper and filter tests over a recorded XTAL response, backend tests over a mock transport, the blueprint's contract suite, one live smoke test |
| `scripts/run_demo.py`, `scripts/demo_drive.js` | The one-command demo; the headed-browser run that produced `docs/demo/` |

## Use it in your own deployment

```python
from shopping_agent import ShoppingAgentConfig
from shopping_agent_runtime import ShoppingAgent
from xtal_commerce_backend import XtalStorefrontBackend

backend = XtalStorefrontBackend(
    "https://www.xtalsearch.com",
    collection="your-collection",
    api_key="xtal_...",       # paid collections; the public demo collection needs none
    is_demo=False,            # production traffic only; see Billing
    timeout=8.0,
    host=None,                # an object with get_cart, get_preferences, ... when you have them
)
agent = ShoppingAgent(
    backend=backend,
    skills_dir=...,           # the blueprint's shopping-agent/skills
    config=ShoppingAgentConfig(
        brand_name="Your Store",
        enable_cart=False, enable_orders=False,
        enable_policies=False, enable_fulfillment=False,
    ),
)
```

Install it with `pip install git+https://github.com/Prompt-Engineering-Inc/claude-commerce-agents-xtal-backend`;
`pyproject.toml` pulls `shopping-agent-core` and `commerce-common` from the pinned upstream
commit. `shopping-agent-runtime` is the blueprint's Messages API loop; install it from the
same clone.

### The switches

Search and product details are the floor of the blueprint. Cart, orders, policies, and
fulfillment are not XTAL's job. Turn each off through the blueprint's `enable_*` config,
which removes those tools and prompt lines on every path. A deployment that has them passes
a `host` object; the backend calls whichever of these methods the object has and answers
the rest itself:

`get_cart`, `add_to_cart`, `update_cart_item`, `remove_from_cart`, `get_preferences`,
`get_orders`, `get_order`, `search_policies`, `get_fulfillment_options`,
`checkout_handoff`, `get_account_context`, `get_disclosure`, `reset_session`.

Without a host: the cart reads as empty and cart writes raise the blueprint's `NotOffered`;
the profile is a guest; orders, policies, and fulfillment options are empty lists.

### Billing

Every search on a paid collection that is not marked `is_demo` is billed per call. The
backend sends `is_demo` as constructed (`True` by default), and so does every test, script,
and demo in this repo. Set `is_demo=False` (or `XTAL_IS_DEMO=0`) only for production traffic
on a collection you are billed for on purpose. The details lookup is a search too, so a
`get_product_details` call costs one search.

## Mapping

| `StorefrontBackend` | XTAL | Notes |
|---|---|---|
| `search_products(session, query, filters, limit)` | `POST /api/xtal/search` | `filters.category` to `facet_filters[category_facet]`; `min_price`/`max_price` to `price_range`; `filters.attributes` to `facet_filters` by tag prefix, values in tag form (`Navy Blue` to `navy-blue`); `sort` to `sort_by`; `limit` clamped to 1..48 |
| `get_product_details(session, product_id)` | a search for the product's title and SKU, `limit` 12, matched on `id` | The title and SKU come from the row a previous search returned; an unknown id is searched as itself. One function, `_resolve`, so it can swap to a product-by-id route when XTAL has one |
| `Product.product_id` | `id` | as a string |
| `Product.title`, `brand`, `currency` | `title` (else `name`), `vendor`, `currency` | |
| `Product.price` | `price` (a number, or the minimum of an array), else the lowest variant price | a row with no price at all is dropped, not given a price |
| `Product.category` | `category`, else `product_type` | |
| `Product.attributes` | `ui_tags` split on the first underscore, then `product_attributes` over them | the field the model reasons with; several tags with one prefix join with commas; `brand` is left out because `Product.brand` carries it |
| `Product.short_description` | `function_description`, else the first 200 characters of `description` | tags stripped |
| `Product.image_url` | `image_url`, else `featured_image`, else `images[0].src` | one URL per row |
| `Product.in_stock` | `available` | |
| `Product.labels` | `on_sale` becomes `"sale"`, plus `price_tier` when present | |
| `ProductDetails.long_description` | `enhanced_description`, else `description` | |
| `ProductDetails.specs` | `product_attributes`, plus `numeric_product_attributes` other than price | |
| `ProductDetails.variants`, `Product.options` | `variants` | a single "Default Title" variant is a plain product; otherwise each variant is a row with id `<product id>:<sku>`, its option values (from `options`, `selected_options`, `option1..3`, or a title like "M / Navy"), price, and stock |
| `rating`, `review_count`, `review_highlights` | none | XTAL carries no review data |

Three things the mapper does beyond the table, each because of something measured against
the live API:

- **The price band is checked on the rows.** XTAL's LLM pipeline applies a `price_range`
  sent as a filter to facet counts but not always to retrieval (for "flannel shirt" with a
  $60 ceiling it returned $69.50 rows). Rows outside the band are dropped, so the agent never
  shows a product over the ceiling the customer stated.
- **An empty filtered search retries without facets.** A `facet_filters` key XTAL has no tag
  prefix for (a category name, an attribute the model guessed) returns zero rows. The retry
  drops the facets and folds the category into the query text, which is how the blueprint's
  own reference backend treats these as soft filters.
- **A price sort reorders the page XTAL returned.** XTAL accepts `sort_by` and ranks by
  relevance; the mapper sorts that page by price when asked, stably, so relevance breaks ties.

### Errors

A 4xx or 5xx from XTAL, a timeout, a connection failure, or a non-JSON body raises
`XtalError`. The blueprint's executor reports it as the tool being temporarily unavailable,
and the model says so instead of guessing. The message never carries the response body.
The blueprint's `Unavailable` is not used: its executor wording is for a cart write
("Nothing was added: ...").

### Logging

One `INFO` line per XTAL call on the `xtal_commerce_backend` logger: collection, query
length, result count, total, XTAL's `query_time` as returned, wall time, and `is_demo`. The
session id reaches XTAL only as a 16-hex-digit digest; on the blueprint's hosts the id is
also the request credential.

## Tests

```bash
ruff check . && ruff format --check . && pytest          # 64 passed, 24 skipped (see below)
XTAL_LIVE=1 pytest tests/test_live.py                    # 3 searches + a max_price check, live
```

`tests/contract/` runs the blueprint's own `examples/demo_common/tests/contract.py` over the
XTAL-backed retail host. The tests of the merchant portal, of the cart and orders (switched
off here), and of a `catalog.json` are skipped by name with the reason; `test_host.py`
carries the storefront half of the ones upstream ties to the portal. The suite runs over a
mock transport serving `tests/fixtures/xtal_search_flag_and_anthem.json`, a recorded
response, or live with `XTAL_LIVE=1`.

## Not here

XTAL has no product-by-id route yet, so details are a search. Nothing is published to PyPI.
No cart or checkout is implemented; a host supplies them. The merchant agent is out of scope.

## License

Apache 2.0, the same license as the blueprint it plugs into.
