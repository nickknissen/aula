"""Tests for aula.models.message_thread."""

import datetime

from aula.models.message_thread import MessageThread

CET = datetime.timezone(datetime.timedelta(hours=1))

# Shaped like one item of a live messaging.getThreads response, with placeholder values.
THREAD = {
    "id": 1000001,
    "subject": "Emne Et",
    "read": False,
    "sensitive": True,
    "startedTime": "2026-11-02T08:15:00+01:00",
    "latestMessage": {
        "id": "1000003",
        "sendDateTime": "2026-11-03T14:30:00+01:00",
        "text": {"html": "<p>Besked Et</p>"},
    },
    "creator": {"fullName": "Lærer Et", "answerDirectlyName": "Lærer Et"},
    "recipients": [
        {
            "fullName": "Værge Et",
            "shortName": "VE",
            "answerDirectlyName": "Værge Et",
            "profilePicture": None,
            "mailBoxOwner": {"id": 1000006, "profileId": 1000007},
        }
    ],
    "regardingChildren": [
        {
            "profileId": 1000008,
            "displayName": "Barn Et",
            "shortName": "BE",
            "profilePicture": {"id": 1000009, "url": "https://example.invalid/picture.jpg"},
        }
    ],
}


def test_thread_dates_from_its_latest_message():
    thread = MessageThread.from_dict(THREAD)
    assert thread.last_updated == datetime.datetime(2026, 11, 3, 14, 30, tzinfo=CET)


def test_thread_read_and_sensitive_flags():
    thread = MessageThread.from_dict(THREAD)
    assert thread.is_read is False
    assert thread.is_sensitive is True


def test_thread_latest_message_is_plain_text():
    latest = MessageThread.from_dict(THREAD).latest_message
    assert latest is not None
    assert latest.id == "1000003"
    assert latest.sent_at == datetime.datetime(2026, 11, 3, 14, 30, tzinfo=CET)
    assert latest.text == "Besked Et"


def test_thread_children_and_recipients():
    thread = MessageThread.from_dict(THREAD)
    assert [(c.profile_id, c.display_name) for c in thread.regarding_children] == [
        (1000008, "Barn Et")
    ]
    assert [(r.full_name, r.short_name) for r in thread.recipients] == [("Værge Et", "VE")]


def test_thread_id_is_a_string():
    assert MessageThread.from_dict(THREAD).thread_id == "1000001"


def test_links_to_the_thread_in_the_web_portal():
    thread = MessageThread.from_dict({"id": 1000001, "subject": "Emne"})

    assert thread.web_url == "https://www.aula.dk/portal/#/beskeder/1000001"


def test_has_no_link_without_a_thread_id():
    assert MessageThread.from_dict({"subject": "Emne"}).web_url is None


def test_dict_conversion_carries_the_link():
    thread = MessageThread(thread_id="1000001", subject="Emne")

    assert dict(thread)["web_url"] == "https://www.aula.dk/portal/#/beskeder/1000001"


def test_thread_without_the_optional_keys():
    thread = MessageThread.from_dict({"id": 1, "subject": "Emne Et"})
    assert thread.thread_id == "1"
    assert thread.last_updated is None
    assert thread.is_read is None
    assert thread.is_sensitive is False
    assert thread.latest_message is None
    assert thread.regarding_children == []
    assert thread.recipients == []


def test_thread_with_an_unreadable_send_date():
    thread = MessageThread.from_dict(
        {**THREAD, "latestMessage": {**THREAD["latestMessage"], "sendDateTime": "i går"}}
    )
    assert thread.last_updated is None
    assert thread.latest_message is not None
    assert thread.latest_message.sent_at is None
