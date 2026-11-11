"""Credential redaction for diagnostic copies, without modifying wire data."""

import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SECRET_FIELDS = {
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "token",
    "authorization",
    "proxyauthorization",
    "cookie",
    "cookies",
    "setcookie",
    "phpsessid",
    "csrftoken",
    "csrfptoken",
    "code",
    "codeverifier",
    "state",
    "password",
    "samlresponse",
    "samlrequest",
    "relaystate",
    "requestverificationtoken",
    "mitidauthcode",
    "sessionuuid",
    "challenge",
}


def diagnostic_url(url: object) -> str:
    """Retain destination and query names; omit credentials and all query values."""
    try:
        parts = urlsplit(str(url))
        authority = parts.netloc.rsplit("@", 1)[-1]
        query = urlencode(
            [(key, "[redacted]") for key, _ in parse_qsl(parts.query, keep_blank_values=True)]
        )
        return urlunsplit((parts.scheme, authority, parts.path, query, ""))
    except ValueError:
        return "[invalid URL]"


def _is_aula_status_code(field: str, item: object) -> bool:
    return field == "code" and isinstance(item, int)


def _is_secret(key: object, item: object) -> bool:
    field = "".join(c for c in str(key).lower() if c.isalnum())
    return field in _SECRET_FIELDS and not _is_aula_status_code(field, item)


def redact_credentials(value: Any) -> Any:
    """Copy nested structures, replacing recognized credential fields before logging."""
    if isinstance(value, BaseException):
        return type(value).__name__
    if isinstance(value, dict):
        return {
            key: "[redacted]" if _is_secret(key, item) else redact_credentials(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_credentials(item) for item in value]
    if isinstance(value, str) and "://" in value:
        return diagnostic_url(value)
    return value


class _CredentialFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Reader parsing warnings and authentication failure logs must use the
        # same redaction as the common response diagnostic. Keep format args
        # separate so formatting cannot turn a nested secret into plain text.
        if isinstance(record.args, tuple):
            record.args = tuple(redact_credentials(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = redact_credentials(record.args)
        if record.exc_info and record.exc_info[0]:
            record.exc_text = record.exc_info[0].__name__
            record.exc_info = None
        return True


def credential_logger(name: str) -> logging.Logger:
    """Build an application logger that sanitizes diagnostic arguments."""
    logger = logging.getLogger(name)
    if not any(isinstance(filter_, _CredentialFilter) for filter_ in logger.filters):
        logger.addFilter(_CredentialFilter())
    return logger
