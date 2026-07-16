#!/usr/bin/env python3
"""
Test helper for the billing and payment info call.

This script exercises ``DukeEnergy.get_billing_payment_info()``, which returns
billing and payment info (balance, dueDate, abbreviatedBillStatus, ...) for
each account.

It reuses tokens saved by ``browser_auth.py`` (``duke_tokens.json``) when
available; otherwise it runs the browser OAuth flow first.

Usage:
    # Include closed accounts (default)
    python billing_payment_info.py

    # Exclude closed accounts
    python billing_payment_info.py --exclude-closed
"""

import asyncio
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any

import aiohttp

from aiodukeenergy_co import (
    Auth0Client,
    DukeEnergy,
    DukeEnergyAuth,
    DukeEnergyAuthError,
)

TOKEN_FILE = Path("duke_tokens.json")


async def _authenticate(
    session: aiohttp.ClientSession, auth0_client: Auth0Client
) -> DukeEnergyAuth:
    """Load tokens from disk or run the browser OAuth flow."""
    auth = DukeEnergyAuth(session, auth0_client)

    if TOKEN_FILE.exists():
        print(f"Loading tokens from {TOKEN_FILE}...")
        with TOKEN_FILE.open() as f:
            tokens = json.load(f)
        auth.restore_token(tokens)
        return auth

    print("No saved tokens found - starting browser OAuth flow.")
    auth_url, _state, code_verifier = auth0_client.get_authorization_url()
    print()
    print("If the browser doesn't open, manually visit this URL:")
    print()
    print(auth_url)
    print()
    webbrowser.open(auth_url)

    print("After logging in, copy the authorization code from the extension.")
    print("Enter the authorization code:")
    code = input("> ").strip()
    if not code:
        print("Error: No code provided")
        sys.exit(1)

    await auth.authenticate_with_code(code, code_verifier)

    with TOKEN_FILE.open("w") as f:
        json.dump(auth.token, f, indent=2)
    print(f"Tokens saved to {TOKEN_FILE}")
    return auth


def _print_account(account_number: str, info: dict[str, Any]) -> None:
    """Pretty-print a single account's billing summary."""
    balance = info.get("balance")
    balance_str = "n/a" if balance is None else f"${balance:.2f}"
    print(f"  Balance:  {balance_str}")
    print(f"  Due date: {info.get('dueDate')}")
    print(f"  Status:   {info.get('abbreviatedBillStatus')}")


async def main() -> None:
    """Fetch and print billing and payment info for every account."""
    include_closed = "--exclude-closed" not in sys.argv[1:]

    print("=" * 60)
    print(f"Duke Energy Billing & Payment Info (include_closed={include_closed})")
    print("=" * 60)
    print()

    async with aiohttp.ClientSession() as session:
        auth0_client = Auth0Client(session)

        try:
            auth = await _authenticate(session, auth0_client)

            client = DukeEnergy(auth)
            info = await client.get_billing_payment_info(include_closed=include_closed)
            print(f"Found {len(info)} account(s).")
            print()

            for account_number, account_info in info.items():
                print("-" * 60)
                print(f"Account {account_number}")
                print("-" * 60)

                _print_account(account_number, account_info)
                print()
                print("Raw response:")
                print(json.dumps(account_info, indent=2))
                print()

        except DukeEnergyAuthError as e:
            print(f"Authentication error: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
