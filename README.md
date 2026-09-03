# claude-commerce-agents-xtal-backend

An [XTAL Search](https://www.xtalsearch.com) backend for Anthropic's open-source
[commerce agents](https://github.com/anthropics/commerce-agents) blueprint.

Anthropic's shopping agent calls a `StorefrontBackend`; its own guidance says the
agent's `search_products` tool should call the retailer's existing search and ranking, so
"the results should arrive already ranked." This package is that backend for any catalog
indexed by XTAL: natural-language product search with per-merchant brand and merchandising
prompts, returned in the blueprint's `Product` shape.

**Status: under construction.** Nothing here runs yet. Watch the repo or come back after the
first release.

## What it will do

- Implement `StorefrontBackend.search_products` and `get_product_details` over the XTAL HTTP API.
- Leave cart, orders, and policies to the host, switched off through the blueprint's own
  `enable_*` switches, with hooks for a host that has them.
- Run Anthropic's ACME retail example, unchanged, over an XTAL-indexed catalog with one
  environment variable.
- Ship contract tests against the blueprint's own test suite, pinned to upstream commit
  `fd4d59224ab9` (2026-08-31).

## License

Apache 2.0, the same license as the blueprint it plugs into.
