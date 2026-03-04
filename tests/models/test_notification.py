"""Tests for aula.models.notification."""

from aula.models.notification import Notification


class TestNotificationFromDict:
    def test_new_message_private_inbox_uses_stripped_message_text(self):
        data = {
            "messageText": (
                "Kære alle forældre på birken 😊<br /><br />"
                "Vi kan desværre ikke finde Conrad\u2019s sovebamse."
            ),
            "senderName": "Linda Charlotte Sørensen",
            "notificationId": "NewMessagePrivateInbox:159531910:Badge",
            "notificationEventType": "NewMessagePrivateInbox",
            "notificationArea": "Messages",
            "notificationType": "Badge",
            "institutionCode": "G19736",
            "expires": "2026-05-31T15:55:16+00:00",
            "triggered": "2026-03-02T15:55:16+00:00",
        }

        n = Notification.from_dict(data)

        assert n.event_type == "NewMessagePrivateInbox"
        assert len(n.title) <= 40
        assert "<br" not in n.title
        assert n.title.startswith("Kære alle forældre")

    def test_post_shared_uses_post_title(self):
        data = {
            "postTitle": "Hoppeland i Smidstrup Hallen d. 9. februar",
            "postId": 12196398,
            "notificationId": "PostSharedWithMe:12196398:Badge",
            "notificationEventType": "PostSharedWithMe",
            "notificationArea": "Posts",
            "notificationType": "Badge",
            "institutionCode": "603004",
            "triggered": "2026-01-19T10:14:29+00:00",
        }

        n = Notification.from_dict(data)

        assert n.title == "Hoppeland i Smidstrup Hallen d. 9. februar"
        assert n.event_type == "PostSharedWithMe"
        assert n.post_id == 12196398
