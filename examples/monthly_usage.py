#!/usr/bin/env python3
"""
Test helper for the summarized monthly usage call.

This script exercises ``DukeEnergy.get_monthly_usage()``, which returns a
usage/bill comparison for this period, the last period, and the same period
one year ago.

It reuses tokens saved by ``browser_auth.py`` (``duke_tokens.json``) when
available; otherwise it runs the browser OAuth flow first.

Usage:
    # Default period is BILLINGCYCLE
    python monthly_usage.py

    # Or pass a period: DAY, WEEK, or BILLINGCYCLE
    python monthly_usage.py WEEK
"""

import asyncio
import json
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp

from aiodukeenergy_co import (
    Auth0Client,
    DukeEnergy,
    DukeEnergyAuth,
    DukeEnergyAuthError,
)

TOKEN_FILE = Path("duke_tokens.json")
VALID_PERIODS = ("DAY", "WEEK", "BILLINGCYCLE")


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


def _print_period(label: str, period: dict) -> None:
    """Pretty-print a single period summary."""
    bill = period.get("bill")
    bill_str = "unbilled" if bill is None else f"${bill:.2f}"
    print(f"  {label}:")
    print(f"    Usage:    {period.get('totalUsage')}")
    print(f"    Bill:     {bill_str}")
    print(f"    Days:     {period.get('days')}")
    print(f"    Avg temp: {period.get('averageTemp')}")


async def main() -> None:
    """Fetch and print summarized monthly usage for every meter."""
    period = sys.argv[1].upper() if len(sys.argv) > 1 else "BILLINGCYCLE"
    if period not in VALID_PERIODS:
        print(f"Invalid period '{period}'. Choose one of: {', '.join(VALID_PERIODS)}")
        sys.exit(1)

    print("=" * 60)
    print(f"Duke Energy Monthly Usage Test (period={period})")
    print("=" * 60)
    print()

    async with aiohttp.ClientSession() as session:
        auth0_client = Auth0Client(session)

        try:
            auth = await _authenticate(session, auth0_client)

            client = DukeEnergy(auth)
            meters = await client.get_meters()
            print(f"Found {len(meters)} meter(s).")
            print()

            # For BILLINGCYCLE, derive each account's cycle start once (latest
            # invoice billEndDate + 1 day) and reuse it across that account's
            # meters instead of fetching invoice-list per meter.
            start_dates: dict[str, datetime | None] = {}

            for serial, meter in meters.items():
                print("-" * 60)
                print(f"Meter {serial} ({meter['serviceType']})")
                print("-" * 60)

                start_date = None
                if period == "BILLINGCYCLE":
                    account_number = meter["account"]["accountNumber"]
                    if account_number not in start_dates:
                        invoices = await client.get_invoices(account_number)
                        start_dates[account_number] = (
                            datetime.strptime(invoices[0]["billEndDate"], "%Y-%m-%d")
                            + timedelta(days=1)
                            if invoices
                            else None
                        )
                    start_date = start_dates[account_number]

                usage = await client.get_monthly_usage(serial, period, start_date)

                _print_period("This period", usage.get("thisPeriod", {}))
                _print_period("Last period", usage.get("lastPeriod", {}))
                _print_period("Same period last year", usage.get("lastYearPeriod", {}))
                print()
                print("Raw response:")
                print(json.dumps(usage, indent=2))
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
