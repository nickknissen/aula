import pytest
from click.testing import CliRunner

from aula.cli import agent_setup


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    return home


def _skill(root):
    return root / "skills" / "aula" / "SKILL.md"


def test_second_run_asks_before_overwriting(home, tmp_path):
    skill = _skill(tmp_path / "project" / ".claude")
    runner = CliRunner()

    first = runner.invoke(agent_setup, [])
    assert first.exit_code == 0
    assert "Overwrite?" not in first.output

    skill.write_text("edited")
    second = runner.invoke(agent_setup, [], input="n\n")
    assert "Overwrite?" in second.output
    assert skill.read_text() == "edited"

    third = runner.invoke(agent_setup, [], input="y\n")
    assert "Overwrite?" in third.output
    assert skill.read_text() != "edited"


def test_force_skips_the_question(home, tmp_path):
    skill = _skill(tmp_path / "project" / ".claude")
    runner = CliRunner()
    runner.invoke(agent_setup, [])
    skill.write_text("edited")

    result = runner.invoke(agent_setup, ["--force"])

    assert "Overwrite?" not in result.output
    assert skill.read_text() != "edited"


def test_opencode_only_writes_to_the_opencode_folder(home, tmp_path):
    (home / ".config" / "opencode").mkdir(parents=True)

    result = CliRunner().invoke(agent_setup, [])

    assert result.exit_code == 0
    assert _skill(tmp_path / "project" / ".opencode").exists()
    assert not (tmp_path / "project" / ".claude").exists()


def test_global_opencode_only_writes_under_config(home):
    (home / ".config" / "opencode").mkdir(parents=True)

    CliRunner().invoke(agent_setup, ["--global"])

    assert _skill(home / ".config" / "opencode").exists()
    assert not (home / ".claude").exists()


def test_both_tools_get_the_skill(home, tmp_path):
    (home / ".claude").mkdir()
    (home / ".config" / "opencode").mkdir(parents=True)

    CliRunner().invoke(agent_setup, [])

    assert _skill(tmp_path / "project" / ".claude").exists()
    assert _skill(tmp_path / "project" / ".opencode").exists()


def test_no_tool_found_still_writes_the_claude_skill(home, tmp_path):
    CliRunner().invoke(agent_setup, [])

    assert _skill(tmp_path / "project" / ".claude").exists()
