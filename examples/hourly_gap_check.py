#!/usr/bin/env python3
"""
Check how Duke answers an HOURLY window that starts before the meter's data.

HOURLY rows carry an hour label but no date, so ``get_energy_usage()`` dates
them by position. If Duke sends only the rows it has for a window that starts
before the first data, every reading in that window is dated too early.

The script only reads data from Duke. For each electric meter it:

1. Finds the first day with data, using single-day requests (a single day
   cannot be misdated), so it works for a new or replaced meter, a service
   start, and the roughly 3-year history limit alike.
2. Requests a window straddling that day and finds where a known day landed.
3. Records what Duke returns for an empty range, for today (not published
   yet), and for a recent range as a control.

It sends about 20 requests per meter, spaced out. It reuses the tokens saved by
``browser_auth.py`` (``duke_tokens.json``) when available; otherwise it runs
the browser OAuth flow first. The token file is the only thing it writes, as
refreshing a token can replace the saved one. Usage is summarized, not printed.

Usage:
    python hourly_gap_check.py

    # Only meters whose serial number ends with these digits
    python hourly_gap_check.py --meter 1234

    # Skip the search and use a known first day with data
    python hourly_gap_check.py --first-day 2025-03-24
"""

import argparse
import asyncio
import json
import os
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp
import yarl
from zoneinfo import ZoneInfo

from aiodukeenergy_co import (
    Auth0Client,
    DukeEnergy,
    DukeEnergyAuth,
    DukeEnergyAuthError,
)

TOKEN_FILE = Path("duke_tokens.json")
TZ = ZoneInfo("America/New_York")
ONE_DAY = timedelta(days=1)

# Days of the straddling window on each side of the first day with data.
STRADDLE_DAYS = 10
# How far back to look for the first day, beyond Duke's roughly 3 years.
SEARCH_DAYS = 5 * 365
# Seconds between requests.
REQUEST_DELAY = 1.0

# 4xx statuses that say nothing about whether the range has data.
NOT_A_REJECTION = (401, 403, 408, 429)


class CheckError(Exception):
    """The check cannot continue."""


@dataclass
class Answer:
    """What Duke returned for one request, and what the library made of it."""

    start: datetime
    end: datetime
    status: int = 0
    body: str = ""
    rows: list[dict[str, Any]] | None = None
    parsed: dict[datetime, dict[str, Any]] = field(default_factory=dict)
    library_error: str | None = None

    @property
    def rejected(self) -> bool:
        """Return True if Duke refused the range itself."""
        return 400 <= self.status < 500 and self.status not in NOT_A_REJECTION

    @property
    def has_usage(self) -> bool:
        """Return True if any row carries usage above zero."""
        return any(_usage(row) > 0 for row in self.rows or [])

    def describe(self) -> str:
        """Summarize the answer without printing usage values."""
        days = (self.end.date() - self.start.date()).days + 1
        text = f"{self.start:%Y-%m-%d} to {self.end:%Y-%m-%d}: HTTP {self.status}"
        if self.status >= 400:
            return f"{text}, {self.body[:200]!r}"
        if self.rows is None:
            return f"{text}, no usageArray, {self.body[:200]!r}"
        text += f", {len(self.rows)} rows (a full answer is about {days * 24})"
        if self.rows:
            zero = sum(_usage(row) <= 0 for row in self.rows)
            text += f", {zero} zero, first row {self.rows[0].get('date')!r}"
        if self.library_error:
            text += f", library raised {self.library_error}"
        return text


def _usage(row: dict[str, Any]) -> float:
    """Return a row's usage, with anything unreadable as 0."""
    try:
        return float(row["usage"])
    except (KeyError, TypeError, ValueError):
        return 0.0


def _keys(rows: list[dict[str, Any]] | None) -> list[tuple[Any, Any]]:
    """Return what identifies each row: its hour label and usage."""
    return [(row.get("date"), row.get("usage")) for row in rows or []]


class RecordingDukeEnergy(DukeEnergy):
    """Client that keeps the raw answer to the last usage request."""

    status = 0
    body = ""

    async def _post_json(
        self,
        url: yarl.URL,
        body: dict[str, Any] | None = None,
        *,
        log_response: bool = True,
    ) -> dict[str, Any]:
        """Post JSON, keeping the status and body of usage requests."""
        if not url.path.endswith("/usage/graph"):
            return await super()._post_json(url, body, log_response=log_response)

        response = await self._auth.request("POST", url, json=body or {})
        self.status = response.status
        self.body = await response.text()
        response.raise_for_status()
        result: dict[str, Any] = json.loads(self.body)
        return result

    async def hourly(self, serial: str, start: datetime, end: datetime) -> Answer:
        """Request an HOURLY window the way the integration does."""
        await asyncio.sleep(REQUEST_DELAY)
        answer = Answer(start, end)
        self.status, self.body = 0, ""
        try:
            result = await self.get_energy_usage(serial, "HOURLY", "DAY", start, end)
            answer.parsed = result["data"]
        except aiohttp.ClientResponseError:
            pass  # Kept as the answer's status and body.
        except (KeyError, TypeError, ValueError, IndexError) as err:
            # An answer the library cannot read is a finding in itself.
            answer.library_error = repr(err)

        answer.status, answer.body = self.status, self.body
        if not answer.status:
            raise CheckError("the request did not reach the usage endpoint")
        if answer.status >= 400 and not answer.rejected:
            raise CheckError(f"HTTP {answer.status} says nothing about the range")
        if 200 <= answer.status < 300:
            try:
                rows = json.loads(answer.body)["usageArray"]
            except (KeyError, TypeError, ValueError):
                rows = None
            answer.rows = rows if isinstance(rows, list) else None
        return answer

    async def day(self, serial: str, day: datetime) -> Answer:
        """Request a single day."""
        return await self.hourly(serial, day, day)


async def find_first_day(
    client: RecordingDukeEnergy, serial: str, today: datetime
) -> datetime | None:
    """Find the first day with usage by bisection, or None if there is no edge."""
    low, high = today - SEARCH_DAYS * ONE_DAY, today - 7 * ONE_DAY
    if not (await client.day(serial, high)).has_usage:
        print(f"  No usage on {high:%Y-%m-%d}; pass --first-day instead.")
        return None
    if (await client.day(serial, low)).has_usage:
        print(f"  There is still usage on {low:%Y-%m-%d}; found no edge.")
        return None

    while high - low > ONE_DAY:
        middle = low + (high - low) // 2
        middle = middle.replace(hour=0, minute=0)
        if (await client.day(serial, middle)).has_usage:
            high = middle
        else:
            low = middle

    # Bisection assumes no empty days after the first one. Landing on a gap in
    # the history would still test a real edge, but a different one.
    for back in (2, 7, 30):
        if (await client.day(serial, high - back * ONE_DAY)).has_usage:
            print(f"  Note: there is also usage {back} days before {high:%Y-%m-%d},")
            print("  so this is a gap in the history, not its start.")
            return None
    return high


def judge(straddle: Answer, first: Answer, marker: Answer) -> tuple[str, str]:
    """Return a verdict and what it means, from where the marker day landed."""
    if straddle.rejected:
        return "REJECTED", "Duke refuses the window. The warning is enough."
    if straddle.library_error:
        return "UNREADABLE", "The library cannot read this answer. Look into it."
    if not straddle.rows:
        return "EMPTY", "Duke sent no rows, so nothing is misdated."

    known, rows = _keys(marker.rows), _keys(straddle.rows)
    if len(known) < 20 or len(set(known)) < 5:
        return "INCONCLUSIVE", "The known day has too little data. Try --first-day."
    places = [i for i in range(len(rows)) if rows[i : i + len(known)] == known]
    if len(places) != 1:
        return "INCONCLUSIVE", f"The known day appears {len(places)} times."

    stored = {
        date.hour: reading["energy"]
        for date, reading in straddle.parsed.items()
        if date.date() == marker.start.date()
    }
    expected = {date.hour: r["energy"] for date, r in marker.parsed.items()}
    before_first = places[0] - len(first.rows or [])
    detail = f"{before_first} rows precede the first day with data. "
    if stored == expected:
        return "PADDED", detail + "The dates are right. The warning is enough."
    return (
        "SHORT",
        detail + "The library misdates this window. Confirm-and-repair is worth it.",
    )


async def check_meter(
    client: RecordingDukeEnergy, serial: str, first_day: datetime | None
) -> None:
    """Run every request for one meter and print the result."""
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    if first_day is None:
        print("  Searching for the first day with data...")
        first_day = await find_first_day(client, serial, today)

    if first_day is not None:
        print(f"  First day with data: {first_day:%Y-%m-%d}")
        first = await client.day(serial, first_day)
        marker = await client.day(serial, first_day + ONE_DAY)
        straddle = await client.hourly(
            serial,
            first_day - STRADDLE_DAYS * ONE_DAY,
            first_day + STRADDLE_DAYS * ONE_DAY,
        )
        empty = await client.hourly(
            serial, first_day - 5 * ONE_DAY, first_day - 3 * ONE_DAY
        )
        print(f"  First day  {first.describe()}")
        print(f"  Known day  {marker.describe()}")
        print(f"  Straddle   {straddle.describe()}")
        print(f"  Empty      {empty.describe()}")

    unpublished = await client.day(serial, today)
    control = await client.hourly(serial, today - 9 * ONE_DAY, today - 7 * ONE_DAY)
    print(f"  Today      {unpublished.describe()}")
    print(f"  Control    {control.describe()}")

    if first_day is not None:
        verdict, meaning = judge(straddle, first, marker)
        print(f"  Verdict: {verdict}. {meaning}")
    else:
        print("  Verdict: none, as there was no first day to straddle.")


async def _authenticate(
    session: aiohttp.ClientSession, auth0_client: Auth0Client
) -> DukeEnergyAuth:
    """Load tokens from disk or run the browser OAuth flow."""
    auth = DukeEnergyAuth(session, auth0_client)

    if TOKEN_FILE.exists():
        print(f"Loading tokens from {TOKEN_FILE}...")
        with TOKEN_FILE.open() as f:
            auth.restore_token(json.load(f))
        if _is_complete(auth):
            return auth
        print("They are incomplete, so signing in again.")

    email = input("Duke Energy sign-in email (Enter to skip): ").strip()
    auth_url, _state, code_verifier = auth0_client.get_authorization_url()
    auth_url = _sign_in_url(auth_url, email)
    print()
    print("If the browser doesn't open, manually visit this URL, unchanged:")
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
    if not _is_complete(auth):
        raise DukeEnergyAuthError(
            "Duke's answer has no ID or refresh token. Was the sign-in URL changed?"
        )
    _save_tokens(auth)
    return auth


def _sign_in_url(auth_url: str, email: str) -> str:
    """
    Return the sign-in URL encoded for a browser, with the email filled in.

    The library's URL has raw spaces in its scope, where a copied or clicked
    link can be cut off. The "email" in that scope is a permission name and has
    to stay; the address to sign in with goes in login_hint.
    """
    auth_url = auth_url.replace(" ", "%20")
    return f"{auth_url}&login_hint={quote(email, safe='')}" if email else auth_url


def _is_complete(auth: DukeEnergyAuth) -> bool:
    """Return True if there are tokens to call and refresh with."""
    token = auth.token or {}
    return bool(token.get("id_token") and token.get("refresh_token"))


def _save_tokens(auth: DukeEnergyAuth) -> None:
    """Save the current tokens, as a refresh can replace the stored ones."""
    if not _is_complete(auth):
        return
    # Readable by the owner only. The mode applies to a new file, and the
    # chmod tightens an existing one before the tokens are written.
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        TOKEN_FILE.chmod(0o600)
        json.dump(auth.token, f, indent=2)


async def main() -> None:
    """Run the check for every electric meter."""
    parser = argparse.ArgumentParser(description="Check HOURLY window dating.")
    parser.add_argument("--meter", default="", help="serial number ending")
    parser.add_argument(
        "--first-day",
        type=lambda text: datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=TZ),
        help="known first day with data (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    async with aiohttp.ClientSession() as session:
        auth = None
        try:
            auth = await _authenticate(session, Auth0Client(session))
            client = RecordingDukeEnergy(auth)
            meters = await client.get_meters()
            serials = [
                serial
                for serial, meter in meters.items()
                if meter["serviceType"] == "ELECTRIC" and serial.endswith(args.meter)
            ]
            print(f"Checking {len(serials)} electric meter(s).")

            for serial in serials:
                meter = meters[serial]
                print()
                print(f"Meter ...{serial[-4:]}")
                print(f"  Agreement active: {meter['agreementActiveDate']}")
                print(f"  Meter certified:  {meter['meterCertificationDate']}")
                try:
                    await check_meter(client, serial, args.first_day)
                except (CheckError, aiohttp.ClientError, TimeoutError) as err:
                    # Not repr(): an HTTP error's repr can include the bearer token.
                    print(f"  Stopped: {type(err).__name__}: {err}. Try again later.")
        except DukeEnergyAuthError as err:
            print(f"Authentication error: {err}")
            sys.exit(1)
        finally:
            if auth is not None:
                _save_tokens(auth)


if __name__ == "__main__":
    asyncio.run(main())
