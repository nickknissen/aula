"""Tests for aula.auth.mitid_client — authenticator choice and credential callbacks."""

import pytest

from aula.auth.exceptions import MitIDError
from aula.auth.mitid_client import MitIDAuthClient


def _client(**kwargs) -> MitIDAuthClient:
    return MitIDAuthClient(mitid_username="tester", **kwargs)


def _returning(value: str):
    async def callback() -> str:
        return value

    return callback


class TestRequireAuthenticator:
    def test_passes_when_available(self):
        MitIDAuthClient._require_authenticator("TOKEN", {"TOKEN": "MitID kodeviser"})

    def test_names_what_the_user_actually_has(self):
        """ "Not available" alone leaves users guessing which method to pick instead."""
        with pytest.raises(MitIDError, match=r"available: APP"):
            MitIDAuthClient._require_authenticator("TOKEN", {"APP": "MitID app"})

    def test_reports_none_when_nothing_is_supported(self):
        with pytest.raises(MitIDError, match=r"available: none"):
            MitIDAuthClient._require_authenticator("APP", {})


class TestTokenDigits:
    @pytest.mark.asyncio
    async def test_accepts_six_digits(self):
        client = _client(on_token_digits=_returning("123456"))

        assert await client._get_token_digits() == "123456"

    @pytest.mark.asyncio
    async def test_strips_surrounding_whitespace(self):
        """Codes get pasted in with a stray space more often than not."""
        client = _client(on_token_digits=_returning("  123456 "))

        assert await client._get_token_digits() == "123456"

    @pytest.mark.asyncio
    async def test_rejects_non_numeric(self):
        client = _client(on_token_digits=_returning("12a456"))

        with pytest.raises(MitIDError, match="numeric"):
            await client._get_token_digits()

    @pytest.mark.asyncio
    async def test_rejects_wrong_length(self):
        client = _client(on_token_digits=_returning("12345"))

        with pytest.raises(MitIDError, match="exactly 6 digits"):
            await client._get_token_digits()

    @pytest.mark.asyncio
    async def test_requires_a_callback(self):
        with pytest.raises(MitIDError, match="on_token_digits"):
            await _client()._get_token_digits()


class TestPassword:
    @pytest.mark.asyncio
    async def test_returns_supplied_password(self):
        client = _client(on_password=_returning("hunter2"))

        assert await client._get_password() == "hunter2"

    @pytest.mark.asyncio
    async def test_rejects_empty(self):
        client = _client(on_password=_returning(""))

        with pytest.raises(MitIDError, match="must not be empty"):
            await client._get_password()

    @pytest.mark.asyncio
    async def test_requires_a_callback(self):
        with pytest.raises(MitIDError, match="on_password"):
            await _client()._get_password()
