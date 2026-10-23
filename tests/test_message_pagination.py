"""Completeness and identity across exhaustive message-reader boundaries."""

from datetime import date
from unittest.mock import AsyncMock

import pytest

from aula.api_client import AulaApiClient
from aula.http import HttpRequestError, HttpResponse


def reader(pages, kind, monkeypatch, *, cap=10):
    monkeypatch.setattr("aula.api_client.MAX_PAGES", cap)
    http = AsyncMock()
    http.request.side_effect = [
        value if isinstance(value, Exception) else HttpResponse(200, {"data": value})
        for value in pages
    ]
    client = AulaApiClient(http)
    if kind == "threads":
        return lambda: client.get_all_message_threads_result(date(2020, 1, 1)), http
    if kind == "messages":
        return lambda: client.get_all_messages_for_thread_result("thread"), http
    return lambda: client.search_messages_result([1], ["INST"], limit=2), http


def page(kind, rows, **metadata):
    if kind == "search":
        rows = [{**row, "searchMessage": row} for row in rows]
    return {
        {"threads": "threads", "messages": "messages", "search": "results"}[kind]: rows,
        **metadata,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["threads", "messages", "search"])
async def test_overlap_retains_first_seen_items_and_confirms_exhaustion(kind, monkeypatch):
    run, _ = reader(
        [
            page(kind, [{"id": "a", "text": "first"}, {"id": "b"}]),
            page(kind, [{"id": "b"}, {"id": "c"}]),
            page(kind, []),
        ],
        kind,
        monkeypatch,
    )
    result = await run()
    assert result.complete is True
    assert result.termination_reason == "exhausted"
    assert [item.id if kind == "search" else item["id"] for item in result.items] == ["a", "b", "c"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["threads", "messages", "search"])
async def test_repeated_page_is_incomplete_without_duplicate_items(kind, monkeypatch):
    rows = [{"id": "a"}, {"id": "b"}]
    run, http = reader([page(kind, rows)] * 3, kind, monkeypatch)
    result = await run()
    assert result.complete is False
    assert result.termination_reason == "no_progress"
    assert len(result.items) == 2
    assert http.request.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["threads", "messages", "search"])
async def test_distinct_page_cap_is_incomplete(kind, monkeypatch):
    run, _ = reader([page(kind, [{"id": "a"}, {"id": "b"}])], kind, monkeypatch, cap=1)
    result = await run()
    assert result.complete is False
    assert result.termination_reason == "max_pages"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["threads", "messages", "search"])
async def test_later_page_failure_still_raises(kind, monkeypatch):
    run, _ = reader(
        [page(kind, [{"id": "a"}, {"id": "b"}]), HttpRequestError("failed", 503)], kind, monkeypatch
    )
    with pytest.raises(HttpRequestError, match="failed"):
        await run()


@pytest.mark.asyncio
async def test_requested_thread_cutoff_is_complete(monkeypatch):
    run, http = reader(
        [
            page(
                "threads",
                [
                    {"id": "new", "lastMessageDate": "2026-01-01"},
                    {"id": "old", "lastMessageDate": "2019-01-01"},
                ],
            )
        ],
        "threads",
        monkeypatch,
    )
    result = await run()
    assert result.complete is True
    assert result.termination_reason == "cutoff"
    assert [item["id"] for item in result.items] == ["new"]
    assert http.request.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["threads", "messages", "search"])
async def test_empty_page_with_unmet_total_is_incomplete(kind, monkeypatch):
    run, _ = reader([page(kind, [], totalSize=10)], kind, monkeypatch)
    result = await run()
    assert result.complete is False
    assert result.termination_reason == "inconsistent_total"


@pytest.mark.asyncio
async def test_idless_distinct_messages_are_preserved(monkeypatch):
    run, _ = reader(
        [page("messages", [{"text": "first"}, {"text": "second"}]), page("messages", [])],
        "messages",
        monkeypatch,
    )
    result = await run()
    assert len(result.items) == 2
    assert result.complete is True


@pytest.mark.asyncio
async def test_short_search_page_cannot_override_a_larger_total(monkeypatch):
    run, _ = reader([page("search", [{"id": "a"}], totalSize=5)], "search", monkeypatch)
    result = await run()
    assert result.complete is False
    assert result.termination_reason == "inconsistent_total"


@pytest.mark.asyncio
async def test_search_deduplication_is_not_evidence_of_exhaustion(monkeypatch):
    run, _ = reader(
        [
            page("search", [{"id": "a"}, {"id": "b"}], totalSize=4),
            page("search", [{"id": "b"}, {"id": "c"}], totalSize=4),
        ],
        "search",
        monkeypatch,
    )
    result = await run()
    assert len(result.items) == 3
    assert result.complete is False
    assert result.termination_reason == "inconsistent_total"
