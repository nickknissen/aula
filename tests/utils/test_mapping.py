"""Tests for aula.utils.mapping."""

from aula.utils.mapping import get_in


def test_reads_a_nested_value():
    assert get_in({"profilePicture": {"url": "http://x"}}, "profilePicture.url") == "http://x"


def test_reads_a_single_key():
    assert get_in({"title": "Heading"}, "title") == "Heading"


def test_null_intermediate_gives_default():
    """Aula sends null, not a missing key, for a child without a picture."""
    assert get_in({"profilePicture": None}, "profilePicture.url", default="") == ""


def test_null_leaf_gives_default():
    """A default means the caller wants a value, not None."""
    assert get_in({"profilePicture": {"url": None}}, "profilePicture.url", default="") == ""


def test_missing_key_gives_default():
    assert get_in({}, "profilePicture.url", default="") == ""


def test_wrong_shape_gives_default():
    assert get_in({"profilePicture": "not-a-dict"}, "profilePicture.url", default="") == ""


def test_none_input_gives_default():
    """Lets callers drop the `if child._raw:` guard around a lookup."""
    assert get_in(None, "institutionProfile.institutionCode", default="") == ""


def test_default_defaults_to_none():
    assert get_in({}, "primaryResource.name") is None


def test_deep_path():
    data = {"data": {"pageConfiguration": {"widgetConfigurations": [1, 2]}}}
    assert get_in(data, "data.pageConfiguration.widgetConfigurations", default=[]) == [1, 2]


def test_falsy_values_are_returned_as_is():
    """Only None is treated as absent, so 0 and "" survive."""
    assert get_in({"a": {"b": 0}}, "a.b", default=99) == 0
    assert get_in({"a": {"b": ""}}, "a.b", default="x") == ""
    assert get_in({"a": {"b": []}}, "a.b", default=[1]) == []
