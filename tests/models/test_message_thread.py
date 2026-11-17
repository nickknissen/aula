"""Tests for aula.models.message_thread."""

from aula.models.message_thread import MessageThread


def test_links_to_the_thread_in_the_web_portal():
    thread = MessageThread.from_dict({"id": 1000001, "subject": "Emne"})

    assert thread.web_url == "https://www.aula.dk/portal/#/beskeder/1000001"


def test_has_no_link_without_a_thread_id():
    assert MessageThread.from_dict({"subject": "Emne"}).web_url is None


def test_dict_conversion_carries_the_link():
    thread = MessageThread(thread_id="1000001", subject="Emne")

    assert dict(thread)["web_url"] == "https://www.aula.dk/portal/#/beskeder/1000001"
