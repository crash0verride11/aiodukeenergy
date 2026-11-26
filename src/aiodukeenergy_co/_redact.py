"""
Keep personal data out of debug logs and error messages.

Redaction is by block list: a field is logged as is unless its name matches a
rule here. Names match at any depth, ignoring case, "_" and "-". Parts and
endings catch renamed fields (billingAddress, contactPhone), so add the general
word where there is one, and an exact name only where there is not.

Empty values (None, blank strings, empty lists and objects) are never replaced,
so a log still shows whether a field had a value.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal

import aiohttp
import yarl
from multidict import CIMultiDict, CIMultiDictProxy

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

_REDACTED = "**REDACTED**"
_TAIL_LENGTH = 4
# Shorter identifiers are redacted whole: their tail would give most of them away.
_MIN_TAILED_LENGTH = 8
# Shorter values are not searched for in text, where they would match by chance.
_MIN_SCRUBBED_LENGTH = 4
_MAX_BODY_LENGTH = 1000

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+(?:@|%40)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"https?://[^\s'\"]+")
_ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")

_Rule = Literal["block", "tail"] | None


def _normalize(name: str) -> str:
    return name.replace("_", "").replace("-", "").casefold()


def _names(*names: str) -> tuple[str, ...]:
    return tuple(map(_normalize, names))


# Never logged. A matching object or list is redacted all the way down.
# Names that contain one of these: serviceAddress, premiseAddress, addressLine1,
# mailingAddressParsed, email, zipCode.
_BLOCKED_PARTS = _names("address", "email", "phone", "zip", "postal")
# Names that end with one of these: primaryBPNumber, relatedBPFirstName,
# primaryBPName, internalUserID, refresh_token.
_BLOCKED_ENDINGS = _names(
    "bpNumber", "bpName", "firstName", "lastName", "fullName", "userId", "token"
)
_BLOCKED = _names("nickname", "city", "stateCode", "codeVerifier")

# Identifiers that keep their last characters, to tell accounts and meters apart.
_TAILED_ENDINGS = _names("accountNumber", "serialNumber")
_TAILED = _names(
    "srcAcctId",
    "srcAcctId2",
    "serialNum",
    "meterNumber",
    "invoiceId",
    "invId",
    "legacyInvId",
    "invArchieveId",  # Duke's spelling
    "hubAccountId",
)


def _rule_for(inherited: _Rule, name: str) -> _Rule:
    if inherited == "block":
        return "block"
    normalized = _normalize(name)
    if (
        normalized in _BLOCKED
        or normalized.endswith(_BLOCKED_ENDINGS)
        or any(part in normalized for part in _BLOCKED_PARTS)
    ):
        return "block"
    if (
        inherited == "tail"
        or normalized in _TAILED
        or normalized.endswith(_TAILED_ENDINGS)
    ):
        return "tail"
    return None


def _redact_value(value: Any, rule: _Rule) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_value(item, _rule_for(rule, str(key)))
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_value(item, rule) for item in value]
    if value is None or (isinstance(value, str) and not value.strip()):
        return value
    if rule == "block":
        return _REDACTED
    if rule == "tail":
        return mask_id(value)
    if isinstance(value, str):
        return _EMAIL.sub(_REDACTED, value)
    return value


def redact(data: Any) -> Any:
    """Return a copy of request or response data that is safe to log."""
    return _redact_value(data, None)


def mask_id(value: object) -> str:
    """
    Shorten an identifier for a log to its last 4 characters, as "...6789".

    One under 8 characters is redacted whole. None and blank values are
    returned as text, so the log shows there was no identifier.
    """
    text = str(value)
    if value is None or not text.strip():
        return text
    if len(text) < _MIN_TAILED_LENGTH:
        return _REDACTED
    return f"...{text[-_TAIL_LENGTH:]}"


def _sensitive_values(data: Any, rule: _Rule = None) -> Iterator[tuple[str, str]]:
    """Yield each value in the data that has a rule, with its replacement."""
    if isinstance(data, dict):
        for key, item in data.items():
            yield from _sensitive_values(item, _rule_for(rule, str(key)))
    elif isinstance(data, list | tuple):
        for item in data:
            yield from _sensitive_values(item, rule)
    elif rule is not None and data is not None:
        yield str(data), _redact_value(str(data), rule)


def redact_body(text: str, sent: Any = None, secrets: Iterable[str | None] = ()) -> str:
    """
    Return a raw response body that is safe to log.

    A JSON body is redacted by field name. An error can also quote the request
    back, in any format, so sensitive values that were sent and anything shaped
    like an email are removed from the text, which is then shortened.

    :param text: The response body.
    :param sent: The request's query parameters or JSON body.
    :param secrets: Further values to remove.
    """
    try:
        text = json.dumps(redact(json.loads(text)))
    except ValueError:
        pass

    replacements = dict(_sensitive_values(sent))
    replacements.update({secret: _REDACTED for secret in secrets if secret})
    # Longest first, so a value that contains another is replaced whole.
    for value in sorted(replacements, key=len, reverse=True):
        if len(value) >= _MIN_SCRUBBED_LENGTH:
            text = text.replace(value, replacements[value])

    return _EMAIL.sub(_REDACTED, text)[:_MAX_BODY_LENGTH]


def summarize_error(status: int, text: str) -> str:
    """Describe a failed request using only its status and any error code."""
    try:
        data = json.loads(text)
    except ValueError:
        return str(status)

    if isinstance(data, dict):
        for name in ("error", "errorCode"):
            code = data.get(name)
            if isinstance(code, str) and _ERROR_CODE.fullmatch(code):
                return f"{status} ({code})"
    return str(status)


def _redact_url(url: yarl.URL) -> yarl.URL:
    if not url.query_string:
        return url
    return url.with_query(
        [
            (key, str(_redact_value(value, _rule_for(None, key))))
            for key, value in url.query.items()
        ]
    )


@contextmanager
def redacted_errors() -> Iterator[None]:
    """
    Redact aiohttp errors raised inside the block.

    Their messages can include the full URL, query and all, and their repr
    includes the request headers, with the bearer token. Each error is changed
    in place, so callers still get the same type, status and other attributes.
    """
    try:
        yield
    except aiohttp.ClientResponseError as err:
        request_info: aiohttp.RequestInfo | None = err.request_info
        if request_info is not None:
            url = _redact_url(request_info.real_url)
            err.request_info = aiohttp.RequestInfo(
                url, request_info.method, CIMultiDictProxy(CIMultiDict()), url
            )
        # Earlier responses of a redirect hold their own URLs and headers.
        err.history = ()
        if isinstance(err.headers, CIMultiDictProxy):
            headers = err.headers.copy()
            headers.popall("Set-Cookie", None)
            err.headers = CIMultiDictProxy(headers)
        err.args = (err.request_info, err.history)
        raise
    except aiohttp.ServerTimeoutError as err:
        # A connect timeout names the URL it was connecting to.
        err.args = tuple(
            _URL.sub(lambda match: str(_redact_url(yarl.URL(match[0]))), arg)
            if isinstance(arg, str)
            else arg
            for arg in err.args
        )
        raise
