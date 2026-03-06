"""Tests for the JSON serialization helper."""

import datetime
import enum
import json
from dataclasses import dataclass, field

from aula.models.base import AulaDataClass
from aula.utils.json import to_json


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


@dataclass
class Inner(AulaDataClass):
    value: int = 0
    _raw: dict = field(default_factory=dict, repr=False)


@dataclass
class Outer(AulaDataClass):
    name: str = ""
    inner: Inner | None = None
    items: list[Inner] = field(default_factory=list)
    _raw: dict = field(default_factory=dict, repr=False)


class TestToJson:
    def test_datetime(self):
        dt = datetime.datetime(2025, 3, 15, 10, 30, 0, tzinfo=datetime.timezone.utc)
        result = json.loads(to_json({"ts": dt}))
        assert result["ts"] == "2025-03-15T10:30:00+00:00"

    def test_date(self):
        d = datetime.date(2025, 3, 15)
        result = json.loads(to_json({"d": d}))
        assert result["d"] == "2025-03-15"

    def test_enum(self):
        result = json.loads(to_json({"color": Color.RED}))
        assert result["color"] == "red"

    def test_aula_dataclass(self):
        obj = Inner(value=42, _raw={"should": "be excluded"})
        result = json.loads(to_json(dict(obj)))
        assert result == {"value": 42}

    def test_nested_dataclass(self):
        obj = Outer(
            name="test",
            inner=Inner(value=1),
            items=[Inner(value=2), Inner(value=3)],
        )
        result = json.loads(to_json(dict(obj)))
        assert result == {
            "name": "test",
            "inner": {"value": 1},
            "items": [{"value": 2}, {"value": 3}],
        }

    def test_list_of_dataclasses(self):
        items = [Inner(value=1), Inner(value=2)]
        result = json.loads(to_json([dict(i) for i in items]))
        assert result == [{"value": 1}, {"value": 2}]

    def test_round_trip(self):
        """Verify that to_json output is valid JSON that can be parsed back."""
        data = {
            "name": "test",
            "date": datetime.date(2025, 1, 1),
            "color": Color.BLUE,
            "items": [1, 2, 3],
        }
        parsed = json.loads(to_json(data))
        assert parsed["name"] == "test"
        assert parsed["date"] == "2025-01-01"
        assert parsed["color"] == "blue"
        assert parsed["items"] == [1, 2, 3]

    def test_unicode_preserved(self):
        result = to_json({"name": "Ærø"})
        assert "Ærø" in result
        parsed = json.loads(result)
        assert parsed["name"] == "Ærø"

    def test_dataclass_via_default(self):
        """AulaDataClass passed directly (not via dict()) is handled by _default."""
        obj = Inner(value=99)
        result = json.loads(to_json({"obj": obj}))
        assert result["obj"] == {"value": 99}
