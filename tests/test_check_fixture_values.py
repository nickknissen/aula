import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "check_fixture_values.py"
_spec = importlib.util.spec_from_file_location("check_fixture_values", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


@pytest.fixture
def invented_name(monkeypatch):
    """Teach the checker a made-up name, so these tests need no real-looking one."""
    monkeypatch.setattr(check, "_NAMES", frozenset({"quillon"}))
    return "Quillon"


def _found(text: str, path: str = "tests/test_x.py", listed=None) -> list[tuple[str, str]]:
    return [(f.kind, f.value) for f in check.check_text(path, text, listed)]


def test_placeholders_pass():
    text = (
        'child = {"name": "Barn Et", "teacher": "Lærer Et", "userId": "barn0001",\n'
        '         "id": 1000001, "code": "900001", "daycare": "G90001", "day": "20260301"}\n'
    )

    assert _found(text) == []


def test_account_shaped_values_are_flagged(invented_name):
    text = (
        'child = {"name": "Quillon", "userId": "quil4821",\n'  # value-check: ok
        '         "id": 4815162, "daycare": "G48151"}\n'  # value-check: ok
    )

    assert _found(text) == [
        ("UniLogin-shaped value", "quil4821"),  # value-check: ok
        ("ID-shaped number", "4815162"),  # value-check: ok
        ("institution code", "G48151"),  # value-check: ok
        ("common name", "Quillon"),
    ]


def test_names_count_only_inside_python_strings_but_anywhere_in_other_files(invented_name):
    text = "quillon = 1  # Quillon\n"

    assert _found(text) == []
    assert _found(text, path="README.md") == [("common name", "Quillon")]


def test_listed_values_match_whole_words_ignoring_case_and_are_masked():
    listed = check._listed_pattern(["Quillon"])
    text = 'a = "quillon"\nb = "Quillonsen"\n'

    assert _found(text, listed=listed) == [("listed value", "qu…")]


def test_a_listed_value_that_also_has_a_shape_is_only_reported_masked(invented_name):
    listed = check._listed_pattern(["4815162", "Quillon"])  # value-check: ok
    text = 'child = {"id": 4815162, "name": "Quillon"}\n'  # value-check: ok

    assert _found(text, listed=listed) == [("listed value", "48…"), ("listed value", "Qu…")]


def test_the_escape_comment_skips_its_line(invented_name):
    text = 'name = "Quillon"  # value-check: ok\n'

    assert _found(text) == []


def test_learn_picks_names_ids_and_codes_from_a_profile():
    profile = {
        "profile_id": 2000001,
        "display_name": "Quillon Vex",
        "children": [
            {
                "id": 1000001,
                "name": "Brin Vex",
                "user_id": "barn0001",
                "institution_name": "Vexby Skole",
                "institution_code": "900001",
                "profile_picture": "https://example.invalid/pic.jpg",
            }
        ],
        "institution_profile_ids": [3000001],
    }

    assert check.learn(profile) == {
        "2000001",
        "Quillon Vex",
        "Quillon",
        "Vex",
        "1000001",
        "Brin Vex",
        "Brin",
        "barn0001",
        "Vexby Skole",
        "Vexby",
        "900001",
        "3000001",
    }


def test_main_fails_on_a_listed_value_without_printing_it(tmp_path, monkeypatch, capsys):
    values = tmp_path / "never-commit.txt"
    values.write_text("Quillon\n", encoding="utf-8")
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"name": "Quillon"}), encoding="utf-8")
    monkeypatch.setenv("AULA_NEVER_COMMIT", str(values))

    assert check.main([str(fixture)]) == 1
    output = capsys.readouterr().out
    assert "listed value: Qu…" in output
    assert "Quillon" not in output
