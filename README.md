# aiodukeenergy-co

<p align="center">
  <a href="https://github.com/crash0verride11/aiodukeenergy/actions/workflows/ci.yml?query=branch%3Aaiodukeenergy-co">
    <img src="https://img.shields.io/github/actions/workflow/status/crash0verride11/aiodukeenergy/ci.yml?branch=aiodukeenergy-co&label=CI&logo=github&style=flat-square" alt="CI Status" >
  </a>
  <a href="https://codecov.io/gh/crash0verride11/aiodukeenergy">
    <img src="https://img.shields.io/codecov/c/github/crash0verride11/aiodukeenergy.svg?logo=codecov&logoColor=fff&style=flat-square" alt="Test coverage percentage">
  </a>
</p>
<p align="center">
  <a href="https://python-poetry.org/">
    <img src="https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json" alt="Poetry">
  </a>
  <a href="https://github.com/astral-sh/ruff">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff">
  </a>
  <a href="https://github.com/pre-commit/pre-commit">
    <img src="https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white&style=flat-square" alt="pre-commit">
  </a>
</p>
<p align="center">
  <a href="https://pypi.org/project/aiodukeenergy-co/">
    <img src="https://img.shields.io/pypi/v/aiodukeenergy-co.svg?logo=python&logoColor=fff&style=flat-square" alt="PyPI Version">
  </a>
  <img src="https://img.shields.io/pypi/pyversions/aiodukeenergy-co.svg?style=flat-square&logo=python&amp;logoColor=fff" alt="Supported Python versions">
  <img src="https://img.shields.io/pypi/l/aiodukeenergy-co.svg?style=flat-square" alt="License">
</p>

---

**Source Code**: <a href="https://github.com/crash0verride11/aiodukeenergy" target="_blank">https://github.com/crash0verride11/aiodukeenergy </a>

---

Asyncio Duke Energy

## Crash Override Edition

I wanted a pip available fork that I could more actively maintain and add api calls to without waiting on pull requests. Includes fixes for gas usage, support for MONTHLY usage requests, and billing and payment information api calls.

## Installation

Install this via pip (or your favourite package manager):

`pip install aiodukeenergy-co`

Import as `aiodukeenergy_co`

## Usage

Duke Energy uses Auth0 with CAPTCHA protection, which blocks automated logins.
You sign in once in a browser, copy the address Duke lands on, and paste it
into the authentication script. The script exchanges it for API tokens.

### Authentication

> On non-iOS devices, you must set the browser's User-Agent to an iPhone.
> Duke rejects desktop browsers after you sign in.

1. Make your browser identify as an iPhone:
   - **Firefox:** `about:config` → add a **String** named
     `general.useragent.override` with the iPhone value below. Firefox has no
     per-site override, so reset the pref when you are done.
   - **Safari Desktop:** enable the Develop menu, then select
     **Develop → User Agent → Safari — iOS ## — iPhone**.
   - **Chrome/Edge:** DevTools (`F12`) → device toolbar (`Ctrl+Shift+M`) →
     iPhone. Device emulation applies per tab, so turn it on in the tab the
     script opens and reload before you sign in.
2. Run the authentication script:

   ```bash
   cd examples
   python browser_auth.py
   ```

3. Enter your Duke Energy email when asked (or press Enter to skip) so the
   sign-in page opens with it filled in. The script opens Duke's sign-in page and
   prints the link if the browser does not open. Sign in, completing any MFA steps.
4. Duke lands on a "Not Found" page whose address ends in `?code=…&state=…`.
5. Copy the **entire** address and paste it into the script. The script checks
   that the address belongs to this sign-in, exchanges the code for tokens,
   and offers to save them to `duke_tokens.json`.
6. If Duke shows `access_denied`, the browser still looked like a desktop.
   Fix the User-Agent and run the script again for a fresh sign-in link.

Keep the script running until you paste the address: each run issues a new,
unique sign-in link. Treat the address as a sign-in credential and keep it
out of issue reports and screenshots.

Example iPhone User-Agent:

```
Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1
```

#### If the sign-in fails

| What you see                                                | Cause                                          | What to do                                                                  |
| ----------------------------------------------------------- | ---------------------------------------------- | --------------------------------------------------------------------------- |
| `access_denied` / "An error has occurred" instead of a code | Duke's login still saw a desktop browser       | Apply the iPhone User-Agent, then run the script again                      |
| "Not Found" page with `code` and `state` in the address     | This is the expected landing page              | Copy the whole address into the script                                      |
| No `code` in the address                                    | Sign-in did not complete                       | Reopen the script's current sign-in link with the iPhone User-Agent applied |
| Code rejected during token exchange                         | Codes expire within minutes and work only once | Run the script again and paste promptly                                     |

### Optional: browser extensions

You don't need an extension. The script also accepts the bare authorization
code that these extensions show.

#### Legacy Chrome extension

The original Chrome extension (`./chrome-extension/`) is no longer needed and
is no longer maintained. It may still work for now but may be removed in
a future release; use the manual steps above instead.

#### Legacy Safari extension

The original Safari extension (`./safari-extension/`) is no longer needed
and is no longer maintained. It may still work for now but may be removed
in a future release; use the manual steps above instead.

Requires Xcode and a free developer account.

- Use the `./safari-extension/` folder from source
- Open the Xcode project
- Go to project settings and set your free developer account as the 'Team' for both Targets (`com.local.duke-energy-oauth-helper` and `com.local.duke-energy-oauth-helper.Extension`). Also ensure 'Signing Certificate' is set to 'Development'
- Quit Safari if open and build the extension
- Open Safari and enable the extension in Safari settings
- Build the extension again
- Enable access to all URLs or a specific URL (https://login.duke-energy.com) in the extension settings

### Using Tokens

Once you have tokens, use them with the library:

```python
import asyncio
import aiohttp
from aiodukeenergy_co import Auth0Client, DukeEnergy, DukeEnergyAuth


async def main():
    # Option 1: Load from token file
    import json

    with open("duke_tokens.json") as f:
        tokens = json.load(f)

    async with aiohttp.ClientSession() as session:
        auth0_client = Auth0Client(session)
        auth = DukeEnergyAuth(
            session,
            auth0_client,
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
            id_token=tokens.get("id_token"),
        )

        client = DukeEnergy(auth)

        accounts = await client.get_accounts()
        print(accounts)

        meters = await client.get_meters()
        for serial, meter in meters.items():
            print(f"Meter: {serial} ({meter['serviceType']})")


asyncio.run(main())
```

### Browser OAuth Flow (Programmatic)

You can also integrate the OAuth flow into your own application:

```python
import asyncio
import webbrowser
import aiohttp
import yarl
from aiodukeenergy_co import Auth0Client, DukeEnergy, DukeEnergyAuth


async def main():
    async with aiohttp.ClientSession() as session:
        auth0_client = Auth0Client(session)
        auth = DukeEnergyAuth(session, auth0_client)

        # Step 1: Get authorization URL with PKCE
        auth_url, state, code_verifier = auth0_client.get_authorization_url()

        # Step 2: Open browser for user login
        webbrowser.open(auth_url)

        # Step 3: Get the code from the callback address the user pastes back
        # (see examples/browser_auth.py for state and error checking)
        callback_url = input("Paste the callback URL: ").strip()
        code = yarl.URL(callback_url).query["code"]

        # Step 4: Exchange code for tokens
        await auth.authenticate_with_code(code, code_verifier)

        # Now you can make API calls
        client = DukeEnergy(auth)
        accounts = await client.get_accounts()
        print(accounts)


asyncio.run(main())
```

### Available Classes

- `Auth0Client` - OAuth2/OIDC client for Duke Energy's Auth0
  - `get_authorization_url()` - Generate browser OAuth URL with PKCE (returns url, state, code_verifier)
  - `exchange_code(code, code_verifier)` - Exchange authorization code for tokens
  - `refresh_token(refresh_token)` - Refresh expired tokens
- `AbstractDukeEnergyAuth` - Abstract base class for auth providers
  - `async_get_id_token()` - Get a valid ID token (abstract)
  - `async_get_access_token()` - Get a valid access token
  - `request(method, url, **kwargs)` - Make authenticated requests
- `DukeEnergyAuth` - Concrete auth implementation using Auth0Client
  - `authenticate_with_code(code, code_verifier)` - Complete OAuth flow
  - `token` - Property to get current token dictionary
- `DukeEnergy` - API client for Duke Energy
  - `get_accounts()` - Get all accounts
  - `get_meters()` - Get all meters
  - `get_energy_usage(meter_serial, interval, view, start_date, end_date)` - Get usage data
  - `get_invoices(account_number)` - Get the account's invoice list (most recent first)
  - `get_invoice_pdf(invoice_id)` - Get a bill as PDF bytes, for an `invId` from `get_invoices` (`None` if there is no PDF). Each is close to 1 MB, so fetch once per invoice
  - `get_billing_payment_info(include_closed=True)` - Get billing/payment info per account (balance, dueDate, abbreviatedBillStatus, ...)
  - `get_monthly_usage(meter_serial, period, start_date)` - Get summarized usage/bill comparison (this period, last period, same period last year). For `BILLINGCYCLE`, pass `start_date` = latest invoice `billEndDate` + 1 day (derive once via `get_invoices` and reuse across meters on the account)

## Contributors ✨

Thanks goes to these wonderful people ([emoji key](https://allcontributors.org/docs/en/emoji-key)):

<!-- prettier-ignore-start -->
<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- markdownlint-disable -->
<!-- markdownlint-enable -->
<!-- ALL-CONTRIBUTORS-LIST:END -->
<!-- prettier-ignore-end -->

This project follows the [all-contributors](https://github.com/all-contributors/all-contributors) specification. Contributions of any kind welcome!

## Credits

This package was created with
[Copier](https://copier.readthedocs.io/) and the
[browniebroke/pypackage-template](https://github.com/browniebroke/pypackage-template)
project template.
