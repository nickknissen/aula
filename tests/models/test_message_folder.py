"""Tests for aula.models.message_folder."""

from aula.models.message_folder import MessageFolder


def test_message_folder_from_dict():
    data = {"id": 1, "name": "Inbox"}
    folder = MessageFolder.from_dict(data)
    assert folder.id == 1
    assert folder.name == "Inbox"
    assert folder._raw is data


def test_message_folder_dict_conversion():
    folder = MessageFolder(id=1, name="Inbox")
    result = dict(folder)
    assert result["id"] == 1
    assert "_raw" not in result
