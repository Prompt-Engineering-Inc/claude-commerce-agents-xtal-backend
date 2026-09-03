# claude-commerce-agents-xtal-backend

Python package implementing Anthropic's `StorefrontBackend` (from github.com/anthropics/commerce-agents)
over the XTAL Search HTTP API. Read `AGENT-PROMPT.md` first; it is the full brief.

## Hard rules
- Every XTAL API call made by tests, scripts, or the demo carries `"is_demo": true` unless
  `XTAL_IS_DEMO=0` is set on purpose. Non-demo searches on a paid collection are billed per call.
- No secrets in the repo. Keys come from `.env` (gitignored); `.env.example` documents the names.
- Upstream is vendored or installed from a pinned commit, never from a floating branch. Bump the
  pin deliberately and re-run the contract tests.
- Do not publish to PyPI and do not change the repository's visibility. Both are Tom's calls.
- Commits and pushes to `main` are fine here; nothing deploys from this repo.
- Never use the WebFetch tool; use `curl` and read the raw page.
- Plain American English in docs, no em dashes, complete sentences, no hype. Never invent numbers.
