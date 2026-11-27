#!/usr/bin/env python3
"""
Browser-based OAuth authentication helper for Duke Energy.

This script handles the OAuth flow for Duke Energy's mobile API:
1. Generates PKCE challenge and opens browser for login
2. User logs in with the browser identifying as an iPhone and copies the
   callback address Duke lands on (a "Not Found" page ending in
   ?code=...&state=...)
3. Script exchanges the authorization code for Duke Energy API tokens

Paste either the full callback URL or just the authorization code (for
example, the code shown by the optional Safari or legacy Chrome extension).
See the README's "Authentication" section for the User-Agent setup.

Usage:
    python browser_auth.py
"""

import asyncio
import json
import sys
import webbrowser
from urllib.parse import quote

import aiohttp
import yarl

from aiodukeenergy_co import (
    Auth0Client,
    DukeEnergy,
    DukeEnergyAuth,
    DukeEnergyAuthError,
)

IPHONE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1"
)


def sign_in_url(auth_url: str, email: str) -> str:
    """
    Return the sign-in URL encoded for a browser, with the email filled in.

    The library's URL has raw spaces in its scope, where a copied or clicked
    link can be cut off. The "email" in that scope is a permission name and has
    to stay; the address to sign in with goes in login_hint.
    """
    auth_url = auth_url.replace(" ", "%20")
    return f"{auth_url}&login_hint={quote(email, safe='')}" if email else auth_url


def parse_code(raw: str, expected_state: str) -> str:
    """
    Return the authorization code from a pasted callback URL or bare code.

    A full callback URL is checked for an authorization error and for a state
    that matches this sign-in attempt. Anything without a query string is
    taken as the code itself.

    :raises ValueError: If the URL is unusable or belongs to another attempt.
    """
    raw = raw.strip()
    if "?" not in raw:
        return raw

    try:
        query = yarl.URL(raw).query
    except ValueError as err:
        raise ValueError("That doesn't look like a valid callback URL.") from err

    if "error" in query:
        detail = query.get("error_description") or query["error"]
        raise ValueError(
            f"Duke rejected the sign-in ({detail}). This usually means the "
            "browser still looked like a desktop. Apply the iPhone User-Agent "
            "and start a fresh sign-in."
        )
    if not (code := query.get("code")):
        raise ValueError("No code in that URL; the sign-in did not complete.")
    if query.get("state") != expected_state:
        raise ValueError(
            "That URL belongs to a different sign-in attempt. Use the link "
            "printed above and paste the new address."
        )
    return code


async def main() -> None:
    """Run the browser-based OAuth flow."""
    print("=" * 60)
    print("Duke Energy Browser OAuth Helper")
    print("=" * 60)
    print()
    print("Before signing in, make your browser identify as an iPhone.")
    print("Duke rejects desktop browsers after authentication:")
    print()
    print("  Firefox: about:config -> String general.useragent.override")
    print("  Safari:  Develop -> User Agent -> Safari - iOS 18 - iPhone")
    print("  Chrome/Edge: DevTools (F12) -> device toolbar -> iPhone, then reload")
    print()
    print("iPhone User-Agent:")
    print(f"  {IPHONE_USER_AGENT}")
    print()

    async with aiohttp.ClientSession() as session:
        # Create Auth0 client
        auth0_client = Auth0Client(session)

        # Step 1: Get authorization URL
        email = input("Duke Energy sign-in email (Enter to skip): ").strip()
        print()
        print("Step 1: Generating authorization URL...")
        auth_url, _state, code_verifier = auth0_client.get_authorization_url()
        auth_url = sign_in_url(auth_url, email)
        # Compare against the state as Duke decodes it from the authorize URL
        # (the raw base64 value's "+" arrives as a space).
        expected_state = yarl.URL(auth_url).query.get("state", "")

        print()
        print("Step 2: Opening browser for login...")
        print()
        print("If the browser doesn't open, manually visit this URL, unchanged:")
        print()
        print(auth_url)
        print()

        # Try to open browser
        webbrowser.open(auth_url)

        print("-" * 60)
        print("INSTRUCTIONS:")
        print("-" * 60)
        print()
        print("1. Log in with your Duke Energy credentials")
        print("2. Complete any MFA/verification steps")
        print('3. Duke lands on a "Not Found" page whose address ends in')
        print("   ?code=...&state=...")
        print("4. Copy the ENTIRE address and paste it below")
        print("   (a bare code from an extension also works)")
        print()
        print("Treat that URL as a sign-in credential: keep it out of issue")
        print("reports and screenshots.")
        print()
        print("Paste the callback URL or authorization code:")
        raw = input("> ").strip()

        if not raw:
            print("Error: Nothing pasted")
            sys.exit(1)

        try:
            code = parse_code(raw, expected_state)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

        print()
        print("Step 3: Exchanging code for Duke Energy tokens...")

        try:
            # Create auth and authenticate
            auth = DukeEnergyAuth(session, auth0_client)
            await auth.authenticate_with_code(code, code_verifier)

            # Get token dict for display/saving
            token_data = auth.token
            access_token = token_data.get("access_token", "") if token_data else ""
            refresh_token = token_data.get("refresh_token", "") if token_data else ""
            id_token = token_data.get("id_token", "") if token_data else ""

            print()
            print("=" * 60)
            print("SUCCESS! Tokens obtained:")
            print("=" * 60)
            print()
            print(f"User ID: {auth.internal_user_id}")
            print(f"Email: {auth.email}")
            print()
            print(f"Access Token ({len(access_token)} chars):")
            print(f"  {access_token[:50]}...{access_token[-20:]}")
            print()
            if refresh_token:
                print(f"Refresh Token ({len(refresh_token)} chars):")
                print(f"  {refresh_token[:50]}...{refresh_token[-20:]}")
                print()

            # Test fetching accounts
            print("-" * 60)
            print("Testing API access - fetching accounts...")
            client = DukeEnergy(auth)
            accounts = await client.get_accounts()
            print(f"Found {len(accounts)} account(s)")
            for account_num in accounts:
                print(f"  - {account_num}")
            print()

            # Offer to save tokens
            print("=" * 60)
            save = input("Save tokens to file? (y/n): ").strip().lower()
            if save == "y":
                filename = "duke_tokens.json"
                with open(filename, "w") as f:
                    json.dump(token_data, f, indent=2)
                print(f"Tokens saved to {filename}")

            print()
            print("Use these tokens with the library:")
            print()
            print("import aiohttp")
            print(
                "from aiodukeenergy_co import Auth0Client, DukeEnergy, DukeEnergyAuth"
            )
            print()
            print("async with aiohttp.ClientSession() as session:")
            print("    auth0_client = Auth0Client(session)")
            print("    auth = DukeEnergyAuth(")
            print("        session,")
            print("        auth0_client,")
            print(f'        access_token="{access_token[:30]}...",')
            print(f'        refresh_token="{refresh_token[:30]}...",')
            print(f'        id_token="{id_token[:30]}...",')
            print("    )")
            print("    client = DukeEnergy(auth)")
            print("    accounts = await client.get_accounts()")

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
