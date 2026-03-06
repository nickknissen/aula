#!/usr/bin/env python3
"""Release script: bumps version, commits, pushes, and creates a GitHub release."""

import re
import subprocess
import sys
from pathlib import Path

PYPROJECT = Path(__file__).parent / "pyproject.toml"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, text=True, capture_output=True, **kwargs)
    if result.returncode != 0:
        print(f"Error running {' '.join(cmd)}:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result


def current_version() -> str:
    content = PYPROJECT.read_text()
    match = re.search(r'^version = "(.+)"', content, re.MULTILINE)
    if not match:
        print("Could not find version in pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def bump_version(old: str, new: str) -> None:
    content = PYPROJECT.read_text()
    updated = content.replace(f'version = "{old}"', f'version = "{new}"', 1)
    PYPROJECT.write_text(updated)


def collect_notes(tag: str) -> str:
    """Use Claude Haiku via CLI to generate release notes from commits since the previous tag."""
    tags = run(["git", "tag", "--sort=-version:refname"]).stdout.strip().splitlines()
    prev_tag = next((t for t in tags if t != tag), None)
    if prev_tag:
        log = run(["git", "log", f"{prev_tag}..HEAD", "--oneline", "--no-merges"]).stdout.strip()
    else:
        log = run(["git", "log", "--oneline", "--no-merges"]).stdout.strip()

    if not log:
        return f"- chore: bump version to {tag.lstrip('v')}"

    prompt = (
        f"Write concise GitHub release notes for version {tag} of an Aula (Danish school platform) "
        f"Python CLI/library. Use a short bullet list grouped by type (feat, fix, chore, etc.). "
        f"Be brief and user-facing. Commits:\n\n{log}"
    )
    result = run(["claude", "-p", "--model", "haiku", prompt])
    return result.stdout.strip()


def main() -> None:
    if len(sys.argv) < 2:
        old = current_version()
        print(f"Usage: python release.py <new-version>  (current: {old})")
        sys.exit(1)

    new_version = sys.argv[1].lstrip("v")
    tag = f"v{new_version}"
    old_version = current_version()

    print(f"Releasing {old_version} → {new_version}")

    # 1. Bump version in pyproject.toml
    bump_version(old_version, new_version)
    print("  Bumped version in pyproject.toml")

    # 2. Sync lockfile
    run(["uv", "sync", "--quiet"])
    print("  Synced uv.lock")

    # 3. Commit
    run(["git", "add", "pyproject.toml", "uv.lock"])
    run(["git", "commit", "-m", f"chore: bump version to {new_version}"])
    print("  Committed version bump")

    # 4. Push
    run(["git", "push", "origin", "main"])
    print("  Pushed to origin/main")

    # 5. Collect release notes and create GitHub release
    notes = collect_notes(tag)
    result = run(["gh", "release", "create", tag, "--title", tag, "--notes", notes])
    url = result.stdout.strip()
    print(f"  Created GitHub release: {url}")


if __name__ == "__main__":
    main()
