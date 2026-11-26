from pathlib import Path

import click

from ..utils.output import (
    echo,
)
from ._app import cli


@cli.command("agent-setup")
@click.option(
    "--global",
    "install_global",
    is_flag=True,
    default=False,
    help="Install skill globally (~/.claude/skills/ or ~/.config/opencode/skills/) "
    "instead of in the current project.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite an existing skill file without asking.",
)
def agent_setup(install_global, force):
    """Install an agent skill so Claude Code / OpenCode can use the Aula CLI.

    Creates a SKILL.md file that teaches AI agents how to query Aula for
    school data.  Works with any tool that follows the Agent Skills standard
    (Claude Code, OpenCode, etc.).
    """
    from ..agent_skill import generate_skill_md

    home = Path.home()
    has_claude = (home / ".claude").is_dir()
    has_opencode = (home / ".config" / "opencode").is_dir()

    skill_roots: list[Path] = []
    if has_claude or not has_opencode:
        skill_roots.append(home / ".claude" if install_global else Path.cwd() / ".claude")
    if has_opencode:
        skill_roots.append(
            home / ".config" / "opencode" if install_global else Path.cwd() / ".opencode"
        )

    content = generate_skill_md()
    installed = False
    for root in skill_roots:
        skill_file = root / "skills" / "aula" / "SKILL.md"
        if (
            skill_file.exists()
            and not force
            and not click.confirm(f"{skill_file} already exists. Overwrite?")
        ):
            echo(f"Skipped: {skill_file}")
            continue
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(content)
        echo(f"Skill installed: {skill_file}")
        installed = True

    if not installed:
        return

    agents: list[str] = []
    if has_claude:
        agents.append("Claude Code")
    if has_opencode:
        agents.append("OpenCode")
    if agents:
        echo(f"Detected: {', '.join(agents)}")
    else:
        echo("No agent tools detected, but the skill file is ready.")

    scope = "globally (all projects)" if install_global else "for this project"
    echo(f"Installed {scope}. Agents can now use /aula or ask about Aula data.")
