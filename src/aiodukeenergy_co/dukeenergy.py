"""
Duke Energy API client.

This module provides a client for interacting with the Duke Energy API.
The client requires an AbstractDukeEnergyAuth instance for authentication.

Example usage:
    async with aiohttp.ClientSession() as session:
        auth0_client = Auth0Client(session)
        auth = DukeEnergyAuth(session, auth0_client)

        # Initial authentication
        auth_url, state, code_verifier = auth0_client.get_authorization_url()
        # ... user logs in and gets code ...
        await auth.authenticate_with_code(code, code_verifier)

        # Create API client
        client = DukeEnergy(auth)
        accounts = await client.get_accounts()
        meters = await client.get_meters()
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

import yarl

if TYPE_CHECKING:
    from .duke_auth import AbstractDukeEnergyAuth

_BASE_URL = yarl.URL("https://api-v2.cma.duke-energy.app")

_DATE_FORMAT = "%m/%d/%Y"

_LOGGER = logging.getLogger(__name__)


class DukeEnergy:
    """
    Duke Energy API client.

    This client provides access to the Duke Energy API for retrieving
    account information, meter data, and energy usage.

    The client requires an AbstractDukeEnergyAuth instance for authentication.
    Use DukeEnergyAuth for the standard OAuth flow, or implement a custom
    subclass of AbstractDukeEnergyAuth for integrations like Home Assistant.

    Example usage:
        # Create auth provider
        auth0_client = Auth0Client(session)
        auth = DukeEnergyAuth(session, auth0_client)

        # Authenticate
        auth_url, state, code_verifier = auth0_client.get_authorization_url()
        # ... user logs in ...
        await auth.authenticate_with_code(code, code_verifier)

        # Create API client and access data
        client = DukeEnergy(auth)
        accounts = await client.get_accounts()
        meters = await client.get_meters()
    """

    def __init__(self, auth: AbstractDukeEnergyAuth) -> None:
        """
        Initialize the Duke Energy API client.

        :param auth: Authentication provider implementing AbstractDukeEnergyAuth.
        """
        self._auth = auth
        self._accounts: dict[str, Any] | None = None
        self._meters: dict[str, Any] | None = None

    @property
    def email(self) -> str | None:
        """Get the email from the auth provider."""
        return self._auth.email

    @property
    def internal_user_id(self) -> str | None:
        """Get the internal user ID from the auth provider."""
        return self._auth.internal_user_id

    async def get_accounts(self, fresh: bool = False) -> dict[str, dict[str, Any]]:
        """
        Get account details from Duke Energy.

        :param fresh: Whether to fetch fresh data.
        :returns: Dictionary of account number to account details.
        """
        if self._accounts and not fresh:
            return self._accounts

        account_list = await self._get_json(
            _BASE_URL.joinpath("account-list"),
            {
                "email": self.email,
                "internalUserID": self.internal_user_id,
                "fetchFreshData": "true",
            },
        )

        accounts = {}
        for account in account_list["accounts"]:
            details = await self._get_json(
                _BASE_URL.joinpath("account-details-v2"),
                {
                    "email": self.email,
                    "srcSysCd": account["srcSysCd"],
                    "srcAcctId": account["srcAcctId"],
                    "primaryBpNumber": account["primaryBpNumber"],
                    "relatedBpNumber": account_list["relatedBpNumber"],
                },
            )
            accounts[account["accountNumber"]] = {
                **account,
                "details": details,
            }

        self._accounts = accounts
        return self._accounts

    async def get_meters(self, fresh: bool = False) -> dict[str, dict[str, Any]]:
        """
        Get meter details from Duke Energy.

        :param fresh: Whether to fetch fresh data.
        :returns: Dictionary of meter serial number to meter details.
        """
        if self._meters and not fresh:
            return self._meters

        if not self._accounts:
            await self.get_accounts(fresh)

        meters = {}
        for account in self._accounts.values() if self._accounts else []:
            for meter in account["details"]["meterInfo"]:
                meters[meter["serialNum"]] = {
                    **meter,
                    "account": {k: v for k, v in account.items() if k != "details"},
                }

        self._meters = meters
        return self._meters

    async def get_energy_usage(
        self,
        serial_number: str,
        interval: Literal["HOURLY", "DAILY", "MONTHLY"],
        period: Literal["DAY", "WEEK", "YEAR", "BILLINGCYCLE"],
        start_date: datetime,
        end_date: datetime,
        include_temperature: bool = True,
    ) -> dict[str, Any]:
        """
        Get energy usage from Duke Energy.

        For HOURLY and DAILY intervals, 'data' maps each interval start to its
        usage and temperature, and 'missing' lists gaps. For MONTHLY (use with
        the YEAR period), 'data' is the raw list of completed billing cycle
        entries, oldest first; the current cycle's start is the last
        entry's endDate plus one day.

        :param serial_number: The serial number of the meter.
        :param interval: The interval (HOURLY, DAILY, or MONTHLY).
        :param period: The period (DAY, WEEK, YEAR, or BILLINGCYCLE).
        :param start_date: The start date.
        :param end_date: The end date.
        :param include_temperature: Whether to include temperature data.
        :returns: Dictionary with 'data' and 'missing' keys.
        """
        if not self._meters:
            await self.get_meters()

        meter = self._meters.get(serial_number) if self._meters else None

        if meter is None:
            raise ValueError(f"Meter {serial_number} not found")

        # Duke uses the selected (start) date with the current date's H:M:S:M
        # as the anchor for HOURLY and DAILY series.
        # Monthly queries instead backdate to yesterday, keeping current time.
        if interval == "MONTHLY":
            graph_date = datetime.now(start_date.tzinfo) - timedelta(days=1)
        else:
            graph_date = datetime.now(start_date.tzinfo).replace(
                year=start_date.year,
                month=start_date.month,
                day=start_date.day,
            )

        result = await self._post_json(
            _BASE_URL.joinpath("account", "usage", "graph"),
            {
                "srcSysCd": meter["account"]["srcSysCd"],
                "srcAcctId": meter["account"]["srcAcctId"],
                "srcAcctId2": meter["account"]["srcAcctId2"] or "",
                "meterSerialNumber": meter["serialNum"],
                "serviceType": meter["serviceType"],
                "intervalFrequency": interval,
                "periodType": period,
                "date": graph_date.isoformat(timespec="milliseconds"),
                "agrmtStartDt": datetime.strptime(
                    meter["agreementActiveDate"], "%Y-%m-%d"
                ).strftime(_DATE_FORMAT),
                "agrmtEndDt": datetime.strptime(
                    meter["agreementEndDate"], "%Y-%m-%d"
                ).strftime(_DATE_FORMAT),
                "meterCertDt": datetime.strptime(
                    meter["meterCertificationDate"], "%Y-%m-%d"
                ).strftime(_DATE_FORMAT),
                "startDate": start_date.strftime(_DATE_FORMAT),
                "endDate": end_date.strftime(_DATE_FORMAT),
                "zipCode": meter["account"]["serviceAddressParsed"]["zipCode"],
            },
        )

        if interval == "MONTHLY":
            # Raw billing cycle entries; the per-interval reconstruction
            # below only applies to HOURLY and DAILY series.
            return {"data": result["usageArray"], "missing": []}

        usage_array = result["usageArray"]
        usage_len = len(usage_array)
        num_expected_values = (end_date - start_date).days + 1

        # Extract temperature data. The API can return fewer rows than the
        # requested window covers (e.g. a window reaching past the meter's
        # data horizon), so never index beyond what actually came back —
        # temp is keyed by row index, so existing rows keep their alignment
        # and absent tail rows fall back to None via the temp_len guard.
        temp = [
            usage_array[i]["temperatureAvg"]
            for i in range(min(num_expected_values, usage_len))
        ]
        temp_len = len(temp)

        # If interval is hourly, multiply the number of values by 24
        if interval == "HOURLY":
            num_expected_values = num_expected_values * 24
            temp = [t for t in temp for _ in range(24)]
            temp_len = len(temp)

        num_values = max(usage_len, num_expected_values)

        data = {}
        missing = []
        offset = 0
        duplicates = 0
        for i in range(num_values):
            delta = (
                timedelta(hours=i - duplicates)
                if interval == "HOURLY"
                else timedelta(days=i)
            )
            date = start_date + delta
            n = i - offset

            expected_series = (
                date.strftime("%I %p")
                if interval == "HOURLY"
                else f"{date.month}/{date.strftime('%d/%Y')}"
            )

            # Past the end of the returned array: the window reached beyond
            # the rows the API sent back, so the remaining dates are missing.
            if n >= usage_len:
                missing.append(date)
                continue

            # Skip duplicate dates
            if n > 0 and usage_array[n]["date"] == usage_array[n - 1]["date"]:
                duplicates += 1
                continue

            # Skip missing dates
            if usage_array[n]["date"] != expected_series:
                missing.append(date)
                offset += 1
                continue

            if not float(usage_array[n]["usage"]) > 0:
                missing.append(date)
                continue

            data[date] = {
                "energy": float(usage_array[n]["usage"]),
                "temperature": temp[n] if n < temp_len else None,
            }

        return {"data": data, "missing": missing}

    async def get_invoices(self, account_number: str) -> list[dict[str, Any]]:
        """
        Get the invoice list for an account, most recent first.

        :param account_number: The account number.
        :returns: List of invoice dictionaries.
        """
        if not self._accounts:
            await self.get_accounts()

        account = self._accounts.get(account_number) if self._accounts else None

        if account is None:
            raise ValueError(f"Account {account_number} not found")

        result = await self._get_json(
            _BASE_URL.joinpath("invoice-list"),
            {
                "srcSysCd": account["srcSysCd"],
                "srcAcctId": account["srcAcctId"],
            },
        )
        return result["invoices"]

    async def get_billing_payment_info(
        self, include_closed: bool = True
    ) -> dict[str, dict[str, Any]]:
        """
        Get billing and payment info for each account.

        Each account includes its balance, dueDate, and abbreviatedBillStatus,
        among other billing and payment details.

        :param include_closed: Whether to include closed accounts.
        :returns: Dictionary of account number to billing and payment info.
        """
        result = await self._get_json(
            _BASE_URL.joinpath(
                "billing-and-payment", "multi-account-payment", "info-v3"
            ),
            {"includeClosedAccounts": "1" if include_closed else "0"},
        )
        return {account["accountNumber"]: account for account in result["accounts"]}

    async def get_monthly_usage(
        self,
        serial_number: str,
        period: Literal["DAY", "WEEK", "BILLINGCYCLE"] = "BILLINGCYCLE",
        start_date: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Get summarized usage and bill comparison from Duke Energy.

        Returns a summary for this period, the last period, and the same
        period one year ago, each with usage, bill, days, and averageTemp.

        For BILLINGCYCLE, ``start_date`` should be the current cycle's start:
        the most recent invoice's ``billEndDate`` plus one day. Fetch invoices
        once with :meth:`get_invoices` and reuse the derived date across meters
        on the same account. When omitted, ``start_date`` defaults to yesterday,
        which only returns the yesterday's usage for 'this bill cycle'.

        :param serial_number: The serial number of the meter.
        :param period: The period (DAY, WEEK, or BILLINGCYCLE).
        :param start_date: The period start date. Defaults to yesterday.
        :returns: Dictionary with 'thisPeriod', 'lastPeriod', and
            'lastYearPeriod' keys.
        """
        if not self._meters:
            await self.get_meters()

        meter = self._meters.get(serial_number) if self._meters else None

        if meter is None:
            raise ValueError(f"Meter {serial_number} not found")

        # endDate is always yesterday; startDate defaults to it when not given.
        end_date = datetime.now() - timedelta(days=1)
        if start_date is None:
            start_date = end_date

        return await self._post_json(
            _BASE_URL.joinpath("account", "usage", "monthly"),
            {
                "srcSysCd": meter["account"]["srcSysCd"],
                "srcAcctId": meter["account"]["srcAcctId"],
                "serviceType": meter["serviceType"],
                "unitOfMeasure": "CCF" if meter["serviceType"] == "GAS" else "KWH",
                "meterNumber": meter["serialNum"],
                "isCertifiedSmartMeter": meter["isCertifiedSmartMeter"],
                "periodType": period,
                "startDate": start_date.strftime(_DATE_FORMAT),
                "endDate": end_date.strftime(_DATE_FORMAT),
                "zipCode": meter["account"]["serviceAddressParsed"]["zipCode"],
            },
        )

    async def _get_json(
        self, url: yarl.URL, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Get JSON from the Duke Energy API.

        :param url: URL to request.
        :param params: Query parameters.
        :returns: JSON response as dictionary.
        """
        _LOGGER.debug("Calling %s with params: %s", url, params)

        response = await self._auth.request("GET", url, params=params or {})
        _LOGGER.debug("Response from %s: %s", url, response.status)
        if not response.ok:
            error_body = await response.text()
            _LOGGER.debug("Error response body from %s: %s", url, error_body)
        response.raise_for_status()
        json_data = await response.json()
        _LOGGER.debug("JSON from %s: %s", url, json_data)
        return json_data

    async def _post_json(
        self, url: yarl.URL, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Post JSON to the Duke Energy API and return JSON response.

        :param url: URL to request.
        :param body: JSON body.
        :returns: JSON response as dictionary.
        """
        _LOGGER.debug("Posting to %s with body: %s", url, body)

        response = await self._auth.request("POST", url, json=body or {})
        _LOGGER.debug("Response from %s: %s", url, response.status)
        if not response.ok:
            error_body = await response.text()
            _LOGGER.debug("Error response body from %s: %s", url, error_body)
        response.raise_for_status()
        json_data = await response.json()
        _LOGGER.debug("JSON from %s: %s", url, json_data)
        return json_data
