from aula.agent_skill import COMMANDS_LEFT_OUT, generate_skill_md
from aula.cli import cli


def test_every_command_is_in_the_skill_or_left_out_on_purpose():
    skill = generate_skill_md()
    missing = [
        name
        for name in cli.commands
        if name not in COMMANDS_LEFT_OUT and f"#### `{name}`" not in skill
    ]
    assert missing == []


def test_left_out_commands_exist_and_are_not_documented():
    skill = generate_skill_md()
    assert set(cli.commands) >= COMMANDS_LEFT_OUT
    assert [name for name in COMMANDS_LEFT_OUT if f"#### `{name}`" in skill] == []


def test_skill_does_not_claim_login_needs_a_person():
    assert "no way to authenticate non-interactively" not in generate_skill_md()
