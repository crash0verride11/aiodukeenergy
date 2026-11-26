"""Tests that personal data stays out of logs and error messages."""

import copy
import json
import logging
import re
import traceback
from datetime import datetime

import aiohttp
import pytest
from aiointercept import aiointercept

from aiodukeenergy_co import (
    AbstractDukeEnergyAuth,
    Auth0Client,
    DukeEnergy,
    DukeEnergyAuthError,
    DukeEnergyBlockedError,
    mask_id,
)
from aiodukeenergy_co._redact import redact, redact_body, summarize_error

# Every sensitive value below contains this, never in its last 4 characters.
MARKER = "zzq"

API = r"https://api-v2\.cma\.duke-energy\.app/"


class FakeAuth(AbstractDukeEnergyAuth):
    def __init__(
        self, session, email=f"{MARKER}@example.com", user_id=f"{MARKER}-user"
    ):
        super().__init__(session)
        self._email = email
        self._internal_user_id = user_id

    async def async_get_id_token(self):
        return f"{MARKER}-id-token"

    async def async_get_access_token(self):
        return f"{MARKER}-bearer-token"


def _url(path):
    return re.compile(API + path + r"(\?.*)?$")


def _address():
    return {
        "addressLine1": f"1 {MARKER} Street",
        "addressLine2": "",
        "city": f"{MARKER}ville",
        "stateCode": f"{MARKER}-state",
        "zipCode": f"{MARKER}-zip",
        # Not on the block list by name; hidden because its parent is.
        "somethingNew": f"{MARKER}-new",
    }


ACCOUNT_NUMBER = f"{MARKER}-account-1111"
SERIAL_NUMBER = f"{MARKER}-serial-2222"
INVOICE_ID = f"{MARKER}-invoice-3333"

ACCOUNT_LIST = {
    "accounts": [
        {
            "accountNumber": ACCOUNT_NUMBER,
            # Duke's casing varies between responses.
            "primaryBPNumber": f"{MARKER}-bp",
            "primaryBPName": f"{MARKER} Person",
            "serviceAddress": f"1 {MARKER} Street",
            "serviceAddressParsed": _address(),
            "mailingAddress": f"2 {MARKER} Road",
            "mailingAddressParsed": _address(),
        }
    ],
    "relatedBpNumber": f"{MARKER}-related",
    "relatedBPFirstName": f"{MARKER}First",
    "relatedBPLastName": f"{MARKER}Last",
    "relatedBPFullName": f"{MARKER}First {MARKER}Last",
}

ACCOUNT_DETAILS = {
    "meterInfo": [
        {
            "serviceType": "ELECTRIC",
            "serialNum": SERIAL_NUMBER,
            "agreementActiveDate": "2000-01-01",
            "agreementEndDate": "2999-01-01",
            "meterCertificationDate": "2020-01-01",
            "isCertifiedSmartMeter": True,
        }
    ],
    "PremiseAddress": _address(),
}


def _assert_clean(text):
    assert MARKER not in text.lower()


class TestRedact:
    def test_names_ignore_case_and_separators(self):
        names = ["primaryBPNumber", "primaryBpNumber", "PRIMARY_BP_NUMBER"]

        assert redact({name: "123" for name in names}) == {
            name: "**REDACTED**" for name in names
        }

    @pytest.mark.parametrize(
        "name",
        [
            "billingAddress",
            "EMAIL_ADDRESS",
            "contactPhoneNumber",
            "postalCode",
            "zip",
            "bpNumber",
            "coApplicantFirstName",
            "userId",
            "id_token",
        ],
    )
    def test_renamed_fields_are_blocked(self, name):
        assert redact({name: "x"}) == {name: "**REDACTED**"}

    def test_renamed_identifiers_keep_last_4(self):
        assert redact(
            {"primaryAccountNumber": "123456789", "ElectricSerialNumber": "987654321"}
        ) == {"primaryAccountNumber": "...6789", "ElectricSerialNumber": "...4321"}

    def test_empty_values_stay_visible(self):
        data: dict[str, object] = {
            "email": None,
            "primaryBPName": "",
            "mailingAddress": "   ",
            "mailingAddressParsed": {},
            "serviceAddress": [],
            "srcAcctId2": "",
            "serviceAddressParsed": {"addressLine1": "1 Main", "addressLine2": ""},
        }

        assert redact(data) == {
            **data,
            "serviceAddressParsed": {
                "addressLine1": "**REDACTED**",
                "addressLine2": "",
            },
        }

    @pytest.mark.parametrize("value", [0, False, 12345, "x"])
    def test_any_other_value_is_redacted(self, value):
        assert redact({"zipCode": value}) == {"zipCode": "**REDACTED**"}

    def test_blocked_list_is_redacted_all_the_way_down(self):
        assert redact({"premiseAddress": [{"anything": "a"}, ""]}) == {
            "premiseAddress": [{"anything": "**REDACTED**"}, ""]
        }

    def test_identifiers_keep_last_4(self):
        assert redact({"accountNumber": "123456789", "InvId": 987654321}) == {
            "accountNumber": "...6789",
            "InvId": "...4321",
        }

    def test_short_identifiers_are_redacted_whole(self):
        assert mask_id("1234567") == "**REDACTED**"
        assert mask_id("12345678") == "...5678"

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_mask_id_shows_there_was_no_identifier(self, value):
        assert mask_id(value) == str(value)

    def test_emails_are_removed_from_unlisted_fields(self):
        assert redact({"message": "Sent to a.b+c@example.com today"}) == {
            "message": "Sent to **REDACTED** today"
        }

    def test_other_values_are_unchanged(self):
        data = {"usageArray": [{"date": "01 AM", "usage": 1.5, "temperatureAvg": 40}]}

        assert redact(data) == data

    def test_input_is_not_changed(self):
        data = copy.deepcopy(ACCOUNT_LIST)

        redact(data)

        assert data == ACCOUNT_LIST

    def test_body_json_is_redacted_by_name(self):
        body = json.dumps({"zip_code": "12345", "refresh_token": "abc", "error": "x"})

        assert json.loads(redact_body(body)) == {
            "zip_code": "**REDACTED**",
            "refresh_token": "**REDACTED**",
            "error": "x",
        }

    def test_body_text_loses_sent_values_secrets_and_emails(self):
        body = (
            "No account 123456789 in 27601 for someone%40example.com"
            " using token-value"
        )

        assert redact_body(
            body,
            {"accountNumber": "123456789", "zipCode": "27601", "srcAcctId2": ""},
            secrets=("token-value", None),
        ) == (
            "No account ...6789 in **REDACTED** for **REDACTED**" " using **REDACTED**"
        )

    def test_body_is_shortened(self):
        assert len(redact_body("a" * 5000)) == 1000

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ('{"error": "invalid_grant", "error_description": "x"}', "invalid_grant"),
            ('{"errorCode": "E-100"}', "E-100"),
            ('{"error": "no account for a@example.com"}', None),
            ('["error"]', None),
            ("<html>", None),
        ],
    )
    def test_summarize_error(self, body, expected):
        assert summarize_error(400, body) == (
            f"400 ({expected})" if expected else "400"
        )


class TestClientLogs:
    @pytest.mark.asyncio
    async def test_every_call_logs_no_personal_data(self, caplog):
        invoices = {"invoices": [{"invId": INVOICE_ID, "legacyInvId": INVOICE_ID}]}
        billing = {
            "accounts": [
                {
                    "accountNumber": ACCOUNT_NUMBER,
                    "serviceAddress": f"1 {MARKER} Street",
                    "nickname": f"{MARKER} house",
                    "dueDate": "2024-07-22",
                }
            ]
        }
        usage = {"usageArray": [{"date": "1/01/2024", "usage": 1, "temperatureAvg": 2}]}

        async with aiohttp.ClientSession() as session:
            async with aiointercept(mock_external_urls=True) as mocked:
                mocked.get(_url("account/list"), payload=ACCOUNT_LIST)
                mocked.post(_url("account/details"), payload=ACCOUNT_DETAILS)
                mocked.post(_url("account/usage/graph"), payload=usage)
                mocked.post(_url("account/usage/comparison"), payload={})
                mocked.post(_url("billing-and-payment/invoice/list"), payload=invoices)
                mocked.post(
                    _url("billing-and-payment/invoice/image"),
                    payload={"imageData": None},
                )
                mocked.get(
                    _url("billing-and-payment/multi-account-payment/info-v3"),
                    payload=billing,
                )

                client = DukeEnergy(FakeAuth(session))
                day = datetime(2024, 1, 1)
                with caplog.at_level(logging.DEBUG, logger="aiodukeenergy_co"):
                    accounts = await client.get_accounts()
                    meters = await client.get_meters()
                    await client.get_energy_usage(
                        SERIAL_NUMBER, "DAILY", "WEEK", day, day
                    )
                    await client.get_monthly_usage(SERIAL_NUMBER)
                    await client.get_invoices(ACCOUNT_NUMBER)
                    await client.get_invoice_pdf(INVOICE_ID)
                    info = await client.get_billing_payment_info()

        logs = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name.startswith("aiodukeenergy_co")
        )
        _assert_clean(logs)
        for tail in ("1111", "2222", "3333"):
            assert f"...{tail}" in logs
        assert "'addressLine2': ''" in logs
        assert "'dueDate': '2024-07-22'" in logs

        # Callers still get the real data.
        account = accounts[ACCOUNT_NUMBER]
        assert account["serviceAddressParsed"] == _address()
        assert account["details"] == ACCOUNT_DETAILS
        assert meters[SERIAL_NUMBER]["serialNum"] == SERIAL_NUMBER
        assert info == {ACCOUNT_NUMBER: billing["accounts"][0]}

    @pytest.mark.asyncio
    async def test_responses_are_not_copied_without_debug_logging(
        self, caplog, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(
            "aiodukeenergy_co.dukeenergy.redact", lambda data: calls.append(data)
        )

        async with aiohttp.ClientSession() as session:
            async with aiointercept(mock_external_urls=True) as mocked:
                mocked.get(_url("account/list"), payload=ACCOUNT_LIST)
                mocked.post(_url("account/details"), payload=ACCOUNT_DETAILS)

                with caplog.at_level(logging.INFO, logger="aiodukeenergy_co"):
                    await DukeEnergy(FakeAuth(session)).get_accounts()

        assert ACCOUNT_LIST not in calls
        assert ACCOUNT_DETAILS not in calls

    @pytest.mark.asyncio
    async def test_error_body_is_redacted(self, caplog):
        async with aiohttp.ClientSession() as session:
            async with aiointercept(mock_external_urls=True) as mocked:
                mocked.get(
                    _url("account/list"),
                    status=400,
                    body=f"Bad request for {MARKER}@example.com {MARKER}-user",
                )

                with caplog.at_level(logging.DEBUG, logger="aiodukeenergy_co"):
                    with pytest.raises(aiohttp.ClientResponseError):
                        await DukeEnergy(FakeAuth(session)).get_accounts()

        assert "Bad request for **REDACTED** **REDACTED**" in caplog.text
        _assert_clean(
            "\n".join(
                record.getMessage()
                for record in caplog.records
                if record.name.startswith("aiodukeenergy_co")
            )
        )


class TestErrors:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("response", "error_type", "status"),
        [
            ({"status": 500}, aiohttp.ClientResponseError, 500),
            (
                {"status": 200, "body": "<html/>", "content_type": "text/html"},
                aiohttp.ContentTypeError,
                200,
            ),
        ],
    )
    async def test_http_error(self, response, error_type, status):
        async with aiohttp.ClientSession() as session:
            async with aiointercept(mock_external_urls=True) as mocked:
                mocked.get(_url("account/list"), **response)

                with pytest.raises(error_type) as caught:
                    await DukeEnergy(FakeAuth(session)).get_accounts()

        err = caught.value
        assert type(err) is error_type
        assert err.status == status
        assert "email=**REDACTED**&internalUserID=**REDACTED**" in str(err)
        assert not err.request_info.headers
        assert err.history == ()
        _assert_clean(str(err))
        _assert_clean(repr(err))
        _assert_clean("".join(traceback.format_exception(err)))

    @pytest.mark.asyncio
    async def test_http_error_shows_an_empty_query_value(self):
        async with aiohttp.ClientSession() as session:
            async with aiointercept(mock_external_urls=True) as mocked:
                mocked.get(_url("account/list"), status=500)

                with pytest.raises(aiohttp.ClientResponseError) as caught:
                    await DukeEnergy(FakeAuth(session, user_id="")).get_accounts()

        assert "internalUserID=&fetchFreshData=true" in str(caught.value)

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        class StalledConnector(aiohttp.BaseConnector):
            async def connect(self, req, traces, timeout):
                raise TimeoutError

        async with aiohttp.ClientSession(connector=StalledConnector()) as session:
            with pytest.raises(aiohttp.ServerTimeoutError) as caught:
                await DukeEnergy(FakeAuth(session)).get_accounts()

        err = caught.value
        assert "email=**REDACTED**" in str(err)
        _assert_clean(repr(err))
        _assert_clean("".join(traceback.format_exception(err)))

    @pytest.mark.asyncio
    async def test_get_user_info_error_has_no_token(self):
        async with aiohttp.ClientSession() as session:
            async with aiointercept(mock_external_urls=True) as mocked:
                mocked.get("https://login.duke-energy.com/userinfo", status=401)

                with pytest.raises(aiohttp.ClientResponseError) as caught:
                    await Auth0Client(session).get_user_info(f"{MARKER}-token")

        assert caught.value.status == 401
        _assert_clean(repr(caught.value))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["exchange_code", "refresh_token"])
    async def test_auth0_error(self, method, caplog):
        body = {
            "error": "invalid_grant",
            "error_description": f"{MARKER}-secret rejected for {MARKER}@example.com",
        }

        async with aiohttp.ClientSession() as session:
            async with aiointercept(mock_external_urls=True) as mocked:
                mocked.post(
                    "https://login.duke-energy.com/oauth/token",
                    status=403,
                    payload=body,
                )
                client = Auth0Client(session)
                args = [f"{MARKER}-secret"]
                if method == "exchange_code":
                    args.append("verifier")

                with caplog.at_level(logging.DEBUG, logger="aiodukeenergy_co"):
                    with pytest.raises(DukeEnergyAuthError) as caught:
                        await getattr(client, method)(*args)

        assert str(caught.value).endswith("failed: 403 (invalid_grant)")
        assert "**REDACTED** rejected for **REDACTED**" in caplog.text
        _assert_clean(
            "\n".join(
                record.getMessage()
                for record in caplog.records
                if record.name.startswith("aiodukeenergy_co")
            )
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("content_type", "error_type"),
        [
            ("application/json", DukeEnergyAuthError),
            ("text/html", DukeEnergyBlockedError),
        ],
    )
    async def test_duke_token_error(self, content_type, error_type, caplog):
        body = f"Refused {MARKER}-id-token {MARKER}@example.com {MARKER}-user"

        async with aiohttp.ClientSession() as session:
            async with aiointercept(mock_external_urls=True) as mocked:
                mocked.post(
                    _url("login/auth-token"),
                    status=403,
                    body=body,
                    content_type=content_type,
                )
                auth = FakeAuth(session)

                with caplog.at_level(logging.DEBUG, logger="aiodukeenergy_co"):
                    with pytest.raises(error_type) as caught:
                        await auth._exchange_for_duke_token(f"{MARKER}-id-token")

        _assert_clean(str(caught.value))
        assert "Refused **REDACTED** **REDACTED** **REDACTED**" in caplog.text
        _assert_clean(
            "\n".join(
                record.getMessage()
                for record in caplog.records
                if record.name.startswith("aiodukeenergy_co")
            )
        )
