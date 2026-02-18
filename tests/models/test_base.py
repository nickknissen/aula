"""Tests for aula.models.base."""

from dataclasses import dataclass, field

from aula.models.base import AulaDataClass


@dataclass
class SampleModel(AulaDataClass):
    name: str = ""
    value: int = 0
    _raw: dict | None = field(default=None, repr=False)


@dataclass
class NestedModel(AulaDataClass):
    child: SampleModel | None = None
    items: list[SampleModel] = field(default_factory=list)
    _raw: dict | None = field(default=None, repr=False)


def test_iter_yields_fields():
    m = SampleModel(name="test", value=42)
    result = dict(m)
    assert result == {"name": "test", "value": 42}


def test_iter_excludes_raw():
    m = SampleModel(name="test", value=1, _raw={"key": "val"})
    result = dict(m)
    assert "_raw" not in result


def test_iter_converts_nested_dataclass():
    inner = SampleModel(name="inner", value=10)
    outer = NestedModel(child=inner)
    result = dict(outer)
    assert result["child"] == {"name": "inner", "value": 10}


def test_iter_converts_list_of_dataclasses():
    items = [SampleModel(name="a", value=1), SampleModel(name="b", value=2)]
    outer = NestedModel(items=items)
    result = dict(outer)
    assert result["items"] == [{"name": "a", "value": 1}, {"name": "b", "value": 2}]


def test_iter_preserves_plain_list_items():
    @dataclass
    class WithPlainList(AulaDataClass):
        tags: list[str] = field(default_factory=list)

    m = WithPlainList(tags=["x", "y"])
    result = dict(m)
    assert result["tags"] == ["x", "y"]


def test_iter_none_child():
    outer = NestedModel(child=None, items=[])
    result = dict(outer)
    assert result["child"] is None
    assert result["items"] == []
