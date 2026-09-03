# Brief for a fresh agent: build the XTAL backend for Anthropic's commerce agents

You are starting in an empty repository, `claude-commerce-agents-xtal-backend`, owned by
Prompt Engineering Inc. (XTAL Search). Read `CLAUDE.md` for the hard rules. This file is the
whole brief; nothing else is assumed.

## Goal

Ship a Python package that implements Anthropic's `StorefrontBackend` over the XTAL Search
HTTP API, so that Anthropic's shopping agent, unchanged, runs over any XTAL-indexed catalog.
Prove it by running Anthropic's ACME retail example against the XTAL demo collection with one
environment variable, in a live conversation, and record that run.

## Context you must read first

1. Anthropic's blueprint: https://github.com/anthropics/commerce-agents (Apache 2.0). Clone it
   at the pinned commit in `.upstream-pin.txt` into `vendor/commerce-agents/` (gitignored).
   Read, in this order: `README.md`, `docs/backends.md`, `docs/safety.md`,
   `shopping-agent/core/shopping_agent/backend.py` (the interface),
   `shopping-agent/core/shopping_agent/types.py` (`Product`, `ProductDetails`, `SearchFilters`),
   `shopping-agent/core/shopping_agent/config.py` (the `enable_*` switches),
   `examples/demo_common/storefront.py` and `storefront_fixtures.py` (the reference backend),
   `examples/demo_common/tests/contract.py` (the contract tests you must pass),
   `examples/retail/api/main.py` (how the retail host picks its backend),
   `shopping-agent/skills/search-discovery/SKILL.md` (how the agent will call you).
2. Anthropic's design notes, read with `curl`, never WebFetch:
   https://claude.com/blog/the-anatomy-of-effective-commerce-agents . The line that matters:
   the agent's `search_products` tool should call the retailer's own search and ranking, and
   "the results should arrive already ranked." Also: "Tool results are context. Return the fields
   the model reasons with and drop the rest. Image URLs on every search row are the usual offender."
3. XTAL's public API docs: https://www.xtalsearch.com/docs/integration (read with curl).

## The XTAL contract

`POST {XTAL_BASE_URL}/api/xtal/search`, JSON body, CORS open, header `X-API-Key: xtal_<48 hex>`
on paid collections (the public demo collection needs no key).

Request fields: `query` (string, required), `collection` (string), `limit` (int),
`offset` (int), `facet_filters` (`{ "<tag prefix>": ["value", ...] }`, for example
`{"color": ["navy"]}` matching tags like `color_navy`), `price_range` (`{"min": number|null,
"max": number|null}`), `search_context` (pass back the object a previous response returned when
paginating or filtering the same query), `sort_by` (string), `session_id` (string),
`search_source` (string; use `"commerce-agent"`), `is_demo` (boolean; REQUIRED true on every
call from tests and the demo).

Response: `results[]`, `total`, `query_time` (ms), `relevance_scores` (by id),
`search_context`, `computed_facets` (`{ "<prefix>": { "<value>": count } }`), `is_sku_search`,
`sku_found`, `top_dense_score`, `redirect_url`.

Each result carries: `id`, `title`, `name`, `description`, `handle`, `vendor`, `product_type`,
`category`, `tags` (raw store tags), `ui_tags` (XTAL's normalized tags, e.g. `color_white`,
`pattern_plaid`, `fit_tailored`), `skus`, `status`, `variants` (each with `price`,
`compare_at_price`, `sku`, options), `price` (a number, or an array of variant prices; use the
minimum), `currency`, `images` (`[{src}]`), `featured_image`, `image_url`, `product_url`,
`enhanced_description`, `form_description`, `function_description`, `on_sale`,
`discount_pct`, `price_tier`, `product_attributes` (`{name: value | [values]}`),
`numeric_product_attributes`, `available`. Payload shape drifts per collection; every field is
optional in your parser.

There is no product-by-id endpoint today. Implement `get_product_details` as a search for the
product's title (and SKU when known) with `limit` 12, matched on `id`; keep the resolver in one
function so it can swap to a dedicated route later.

Verify the contract yourself before writing the mapper: run one real call with
`is_demo: true` against `flag-and-anthem` and save the raw JSON under `tests/fixtures/`.

## Mapping

| `StorefrontBackend` | XTAL | Notes |
|---|---|---|
| `search_products(session, query, filters, limit)` | `POST /api/xtal/search` | `filters.category` to `facet_filters`, `min_price`/`max_price` to `price_range`, `filters.attributes` to `facet_filters` by tag prefix, `sort` to `sort_by`, `limit` clamped to the config cap |
| `get_product_details(session, product_id)` | title/SKU search matched on id | `long_description` from `enhanced_description`, then `description`; `specs` from `product_attributes`; `variants` from `variants` |
| `Product.attributes` | `ui_tags` split on the first underscore plus `product_attributes` | this is the field the model reasons with; keep it |
| `Product.short_description` | `function_description`, else the first 200 chars of `description` | |
| `Product.image_url` | `image_url`, else `featured_image`, else `images[0].src` | one URL per row, as the deep-dive says |
| `Product.in_stock` | `available` | |
| `Product.labels` | `on_sale` becomes `"sale"`, plus `price_tier` when present | |
| cart, orders, policies, preferences, fulfillment, disclosures, account context | not XTAL's job | off by default through the blueprint's `enable_*` switches; expose an optional `host` object a deployment can pass to supply them |

## Package

- Name `xtal-commerce-backend`, import `xtal_commerce_backend`, Python 3.11+, `httpx`, `pydantic`.
- `XtalStorefrontBackend(base_url, collection, api_key=None, is_demo=True, timeout=8.0, host=None)`.
- One module for the HTTP client, one for the mapper, one for the backend class. No logic in the
  backend class beyond calling the two.
- Depend on `shopping-agent-core` from the pinned upstream commit (git URL in `pyproject.toml`),
  never from a floating branch.
- Honest errors: a 4xx or 5xx from XTAL raises the blueprint's `Unavailable`; a timeout too. The
  model then says so instead of guessing.
- Log one INFO line per XTAL call: collection, query length, result count, `query_time`, and
  whether `is_demo` was set.

## Tests, all required

1. Unit tests for the mapper against the saved fixture: field by field, including the
   price-as-array case and a product with variants.
2. Filter translation tests: category, price band, attribute, sort, pagination with
   `search_context`.
3. The blueprint's contract tests from `examples/demo_common/tests/contract.py` run against
   `XtalStorefrontBackend` with cart, orders, and policies switched off.
4. One live smoke test, marked `live`, skipped unless `XTAL_LIVE=1`: three searches with
   `is_demo: true` against `flag-and-anthem`, asserting non-empty ranked results and that a
   `max_price` filter is honored.
5. `ruff check` and `ruff format --check` clean.

## The demo, which is the point

Wire Anthropic's retail example to this backend without editing upstream files: an
`examples/retail_on_xtal/` host that imports upstream's retail API app and swaps the backend
when `XTAL_COLLECTION` is set. Then run it:

```
python scripts/run_demo.py retail   # from vendor/commerce-agents, with your host on the path
```

Drive the storefront in a real browser (Playwright, headed) through the retail README's three
turns adapted to the catalog, for example "I need a warm shirt for a fall bonfire, under $80",
then "compare the top two", then "which one has stretch". Save screenshots to `docs/demo/`.
Record what the agent asked XTAL (the queries and filters it chose) in `docs/demo/RUN.md`, with
the numbers as measured: XTAL `query_time`, and time to first token per turn. Do not round up.

## README, written for the person who will screenshot it

Front-load the recipe: clone, install, set `XTAL_COLLECTION`, run, and what you see. Then the
mapping table above, the switches, how to point it at your own XTAL collection with an API key,
and the billing line: every non-demo search is billed per call. Plain American English, no
em dashes, no hype, no invented figures. Link the blueprint and Anthropic's deep-dive.

## Out of scope

The product-by-id route on XTAL's side, publishing to PyPI, changing the repo's visibility,
and any cart or checkout implementation.

## Report when done

Commits with one line each; the contract-test result; the live smoke result; the demo run's
measured numbers; anything you could not do and why. Never report green you did not see.
