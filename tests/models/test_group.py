"""Tests for aula.models.group."""

from aula.models.group import Group, GroupMember


class TestGroup:
    def test_group_from_dict(self):
        data = {
            "id": 1,
            "name": "Class 3A",
            "type": "primary",
            "institutionCode": "123456",
            "description": "Main class group",
        }
        group = Group.from_dict(data)
        assert group.id == 1
        assert group.name == "Class 3A"
        assert group.group_type == "primary"
        assert group.institution_code == "123456"
        assert group.description == "Main class group"
        assert group._raw is data

    def test_group_from_dict_missing_optional(self):
        data = {"id": 2, "name": "Group B"}
        group = Group.from_dict(data)
        assert group.group_type == ""
        assert group.institution_code == ""
        assert group.description == ""

    def test_group_dict_conversion(self):
        group = Group(id=1, name="Test", group_type="primary", institution_code="ABC")
        result = dict(group)
        assert result["id"] == 1
        assert result["name"] == "Test"
        assert "_raw" not in result


class TestGroupMember:
    def test_group_member_from_dict(self):
        data = {
            "institutionProfileId": 42,
            "name": "Alice Smith",
            "portalRole": "guardian",
        }
        member = GroupMember.from_dict(data)
        assert member.institution_profile_id == 42
        assert member.name == "Alice Smith"
        assert member.portal_role == "guardian"
        assert member._raw is data

    def test_group_member_from_dict_missing_optional(self):
        data = {"institutionProfileId": 99, "name": "Bob"}
        member = GroupMember.from_dict(data)
        assert member.portal_role == ""

    def test_group_member_dict_conversion(self):
        member = GroupMember(institution_profile_id=1, name="Test")
        result = dict(member)
        assert result["institution_profile_id"] == 1
        assert result["name"] == "Test"
        assert "_raw" not in result
