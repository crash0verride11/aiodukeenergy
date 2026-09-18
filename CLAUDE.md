# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`aiodukeenergy-co` is an asyncio client for Duke Energy's mobile API (`api-v2.cma.duke-energy.app`). It is a published fork of `hunterjm/aiodukeenergy` — the import name is `aiodukeenergy_co` (under `src/`) and the PyPI distribution is `aiodukeenergy-co`.

## Commands

Tooling is Poetry + Ruff + pytest. Tests are commonly run through `uvx` to avoid managing a local env.

```bash
# Full test suite (see pin note below)
uvx --python 3.12 --with pytest --with aioresponses --with 'aiohttp<3.12' --with pytest-cov --with pytest-asyncio --with PyJWT pytest tests/ -v

# Single test
uvx --python 3.12 --with pytest --with aioresponses --with 'aiohttp<3.12' --with pytest-cov --with pytest-asyncio --with PyJWT pytest "tests/test_init.py::TestUsageAPI::test_monthly_usage" -v

# Lint + format (pin ruff to match CI / pre-commit)
uvx ruff@0.6.4 check src/ tests/
uvx ruff@0.6.4 format --check src/ tests/
```

**Dependency pin gotcha:** without `--python 3.12` and `aiohttp<3.12`, `uvx` resolves aiohttp 3.12+ on Python 3.14, which is incompatible with `aioresponses` 0.7.x and fails ~16 tests with `ClientResponse.__init__() missing 1 required keyword-only argument: 'stream_writer'`. That error is an environment mismatch, not a real regression.

For a local env instead of `uvx`: `python3.12 -m venv ./.venv && source ./.venv/bin/activate && pip install -e . && pip install pytest aioresponses 'aiohttp<3.12' pytest-cov pytest-asyncio PyJWT`, then run `pytest` directly.

All tests live in a single file, `tests/test_init.py`, and use `aioresponses` to mock the HTTP layer plus a `MockAuth`/hand-built JWT helper (`_create_test_jwt`) for auth. There is no live-network test path.

## Architecture

The library is layered so that auth concerns are fully separated from the API client. Understanding this separation is the key to working here.

**Auth stack (bottom to top):**
- `auth0.py` — `Auth0Client`: pure Auth0 OAuth2/OIDC (PKCE authorization URL, code exchange, refresh, userinfo) plus stateless JWT helpers (`decode_token`, `is_token_expired`, `extract_code_from_url`). Knows nothing about Duke Energy's API.
- `duke_auth.py` — `AbstractDukeEnergyAuth`: holds the **second** token. Duke's API does not accept the Auth0 token directly; `_exchange_for_duke_token()` trades the Auth0 `id_token` for a Duke API access token via `/login/auth-token` (Basic auth with the hardcoded mobile-app client id/secret). This DE token is cached with its own expiry and re-exchanged lazily in `async_get_access_token()`. `request()` is the single authenticated-HTTP entry point every API call goes through.
- `duke_auth.py` — `DukeEnergyAuth`: concrete subclass wiring `Auth0Client` in. Implements `async_get_id_token()` with automatic Auth0 refresh, and adds token persistence via the `token` property + `restore_token()`. Subclass `AbstractDukeEnergyAuth` (not `DukeEnergyAuth`) for embeddings like Home Assistant that manage their own OAuth session.

**API client:** `dukeenergy.py` — `DukeEnergy` takes any `AbstractDukeEnergyAuth` and contains **no auth logic**. All requests funnel through `_get_json()` / `_post_json()`, which delegate to `auth.request()`. `get_accounts()` and `get_meters()` memoize their results on the instance (`self._accounts` / `self._meters`); pass `fresh=True` to bypass. `get_meters()` flattens every account's `meterInfo` into a `{serialNum: meter}` dict and stamps each meter with a back-reference to its parent account under `meter["account"]`, so downstream usage methods read account fields (`srcSysCd`, `srcAcctId`, `zipCode`) off the meter.

Exceptions form a small hierarchy in `exceptions.py`: `DukeEnergyError` → `DukeEnergyAuthError` → `DukeEnergyTokenExpiredError`. `DukeEnergyBlockedError` is a **sibling** of `DukeEnergyAuthError` (direct subclass of `DukeEnergyError`), raised by `_exchange_for_duke_token()` when the response is non-JSON — i.e. an edge/WAF refusal (Akamai "Access Denied") that never reached Duke's API. It is deliberately not an auth error so consumers don't map it to reauth; content type, not status code, is the discriminator.

## API-specific conventions

- **Dates:** the Duke API uses `%m/%d/%Y` (`_DATE_FORMAT`). Endpoints are quirky about the `date`/`startDate`/`endDate` fields — see the inline comments in `get_energy_usage`, which reconstructs the `date` param from "now" with the start date's year/month/day and reconciles the returned `usageArray` against expected series, detecting missing days and DST-duplicate hours.
- **`unitOfMeasure`:** derived from `serviceType` — `CCF` for `GAS`, `KWH` otherwise. CCF is confirmed as Duke's only gas unit.
- **Monthly billing-cycle start:** `/account/usage/monthly` (via `get_monthly_usage`) needs the current cycle's `startDate`. Duke derives this as **the most recent invoice's `billEndDate` + 1 day**; fetch it once with `get_invoices()` and reuse across meters on the same account (see `examples/monthly_usage.py`). `endDate` is always yesterday; when `start_date` is omitted it also defaults to yesterday, returning only yesterday's usage for the current cycle.

## Auth flow for manual testing

Duke's Auth0 has CAPTCHA that blocks headless login, so obtaining tokens requires a browser + the bundled Chrome/Safari extension to capture the redirect code. `examples/browser_auth.py` runs that flow and writes `duke_tokens.json`; other example scripts (e.g. `examples/monthly_usage.py`) restore from that file via `auth.restore_token(...)`. See README "Setup" for extension installation.

## Release model

This is a fork published as its own package, with an unusual branch/release setup — do not assume standard `main`-based releasing:

- **Release branch is `aiodukeenergy-co`** (the default branch), gated in `.github/workflows/ci.yml` and `[tool.semantic_release.branches.release]`. `main` is kept in sync with upstream `hunterjm/aiodukeenergy` and does **not** release.
- Versioning is automated by **python-semantic-release** from Conventional Commits; publishing is PyPI Trusted Publishing (OIDC) via the `release` GitHub environment (no tokens in-repo).
- `commit_parser_options.ignore_merge_commits = true` is required — syncing `main` from upstream produces non-conventional merge commits that otherwise crash the changelog template.
- PyPI version lineage started fresh at **1.0.0**; upstream's historical tags are not on this fork's `origin`, so don't treat a local `v1.x` tag as published.

Commits should follow Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `docs:`) since the changelog and version bumps are derived from them.
