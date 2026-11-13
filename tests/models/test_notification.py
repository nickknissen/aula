"""Tests for aula.models.notification."""

from aula.models.notification import Notification


class TestNotificationFromDict:
    def test_new_message_private_inbox_uses_stripped_message_text(self):
        data = {
            "messageText": (
                "Kære alle forældre på stuen 😊<br /><br />"
                "Vi kan desværre ikke finde Barn Et\u2019s sovebamse."
            ),
            "senderName": "Lærer Et",
            "notificationId": "NewMessagePrivateInbox:3000002:Badge",
            "notificationEventType": "NewMessagePrivateInbox",
            "notificationArea": "Messages",
            "notificationType": "Badge",
            "institutionCode": "G90001",
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
            "postTitle": "Hoppeland i hallen d. 9. februar",
            "postId": 3000001,
            "notificationId": "PostSharedWithMe:3000001:Badge",
            "notificationEventType": "PostSharedWithMe",
            "notificationArea": "Posts",
            "notificationType": "Badge",
            "institutionCode": "900001",
            "triggered": "2026-01-19T10:14:29+00:00",
        }

        n = Notification.from_dict(data)

        assert n.title == "Hoppeland i hallen d. 9. februar"
        assert n.event_type == "PostSharedWithMe"
        assert n.post_id == 3000001
