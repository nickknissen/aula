"""Tests for aula.cli helpers."""

import pytest

from aula.cli import CONTACTS_PAGE_SIZE, MAX_CONTACT_PAGES, _fetch_contact_pages


def _pager(total: int):
    """Return a fetch_page callable serving ``total`` items in 20-item pages."""
    calls: list[int] = []

    async def fetch_page(page: int) -> list[dict]:
        calls.append(page)
        start = (page - 1) * CONTACTS_PAGE_SIZE
        return [{"id": i} for i in range(start, min(start + CONTACTS_PAGE_SIZE, total))]

    return fetch_page, calls


class TestFetchContactPages:
    @pytest.mark.asyncio
    async def test_walks_every_page_until_a_short_one(self):
        fetch_page, calls = _pager(45)

        result = await _fetch_contact_pages(fetch_page)

        assert len(result) == 45
        assert calls == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_stops_on_first_empty_page_when_total_is_a_multiple(self):
        """A full last page can't be detected as final, so one extra call happens."""
        fetch_page, calls = _pager(40)

        result = await _fetch_contact_pages(fetch_page)

        assert len(result) == 40
        assert calls == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_single_page_makes_one_call(self):
        fetch_page, calls = _pager(5)

        result = await _fetch_contact_pages(fetch_page)

        assert len(result) == 5
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_explicit_page_fetches_only_that_page(self):
        fetch_page, calls = _pager(100)

        result = await _fetch_contact_pages(fetch_page, page=3)

        assert calls == [3]
        assert [item["id"] for item in result] == list(range(40, 60))

    @pytest.mark.asyncio
    async def test_warns_instead_of_looping_forever(self, capsys):
        """A server that never returns a short page must not spin indefinitely."""
        calls: list[int] = []

        async def always_full(page: int) -> list[dict]:
            calls.append(page)
            return [{"id": page}] * CONTACTS_PAGE_SIZE

        result = await _fetch_contact_pages(always_full)

        assert len(calls) == MAX_CONTACT_PAGES
        assert len(result) == MAX_CONTACT_PAGES * CONTACTS_PAGE_SIZE
        assert "may be incomplete" in capsys.readouterr().out
